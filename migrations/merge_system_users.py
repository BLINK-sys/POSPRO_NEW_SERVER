"""
Слияние двух системных юзеров (дубль → основной).

Все записи, где `src` юзер был creator/responsible/author/member/watcher/...
переставляются на `dst`. Для таблиц с unique-ограничениями (например
chat_member, task_watcher) — сначала удаляются «дубль-строки» src, где
на этом же ключе уже сидит dst, потом UPDATE оставшихся. В конце —
опционально удаляется сам src-юзер, и его email записывается в
system_user_email_alias → user_id dst, чтобы следующий B24-импорт
не создал дубль заново.

Dry-run по умолчанию (ничего не меняет, печатает что бы сделал).
С `--apply` всё коммитится одной транзакцией.

Запуск через Render Job:
    python -u -m migrations.merge_system_users --src ant@pospro.kz --dst bocan.anton@mail.ru
    python -u -m migrations.merge_system_users --src ant@pospro.kz --dst bocan.anton@mail.ru --apply --delete-src
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text, exc as sa_exc


# ---------------------------------------------------------------------------
# Таблицы с «простым» ownership — одна FK-колонка на system_users без
# unique-constraint, в котором участвует user_id. Чистый UPDATE.
# ---------------------------------------------------------------------------
PLAIN_UPDATES: list[tuple[str, str]] = [
    # deals / tasks ownership
    ('deal',              'responsible_user_id'),
    ('deal',              'creator_id'),
    ('deal_activity',     'user_id'),
    ('deal_kp',           'attached_by'),
    ('task',              'responsible_id'),
    ('task',              'creator_id'),
    ('task_activity',     'user_id'),
    # chat (автор/приколовший) — unique ниже отдельно
    ('chat_message',      'author_id'),
    ('chat_message',      'pinned_by'),
    # notifications (CASCADE on delete, но мы переставляем, не удаляем)
    ('notification',      'user_id'),
    ('web_push_subscription', 'user_id'),
    # misc
    ('ai_import_logs',    'user_id'),
    ('ai_chat_sessions',  'user_id'),
    ('ai_chat_messages',  'user_id'),
    ('collector_task',    'owner_id'),
    ('deal_pipeline_viewer', 'user_id'),
    ('crm_ingest_source', 'fixed_user_id'),
    ('crm_ingest_source', 'created_by'),
    ('entity_attachment', 'uploaded_by'),
    ('project',           'created_by'),
    ('order_managers',    'manager_id'),
    ('order_managers',    'assigned_by'),
    # KP: user_id без FK, но хранит system_user id когда user_role='admin'
    # (клиенты не трогаем — у них user_role='client'). Поэтому UPDATE только
    # где user_role='admin'. Делаем это отдельным SQL ниже (см. KP_HISTORY_SQL).
]


# ---------------------------------------------------------------------------
# Таблицы с unique/PK, где участвует user_id. Нужен сначала DELETE src,
# где уже существует (dst, other_cols) — иначе UPDATE упадёт на unique.
# other_cols — остальные колонки unique-ключа.
# ---------------------------------------------------------------------------
UNIQUE_TABLES: list[tuple[str, str, list[str]]] = [
    ('deal_member',    'user_id',             ['deal_id']),
    ('task_member',    'user_id',             ['task_id']),
    ('task_watcher',   'user_id',             ['task_id']),
    ('chat_member',    'user_id',             ['room_id']),
    ('chat_reaction',  'user_id',             ['message_id', 'emoji']),
    ('user_preferences','user_id',            ['key']),
    ('kp_share',       'shared_with_user_id', ['kp_history_id']),
    ('kp_settings',    'user_id',             ['user_role']),
    # user_presence: PK = user_id (один к одному), просто удалим src
    ('user_presence',  'user_id',             []),
]


# Отдельно: kp_history.user_id — без FK, но системный id когда role='admin'
KP_HISTORY_UPDATE = (
    "UPDATE kp_history SET user_id = :dst "
    "WHERE user_id = :src AND user_role = 'admin'"
)
KP_HISTORY_COUNT = (
    "SELECT COUNT(*) FROM kp_history "
    "WHERE user_id = :src AND user_role = 'admin'"
)


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--src', required=True, help='Email источника (кого вливаем)')
    p.add_argument('--dst', required=True, help='Email целевого юзера')
    p.add_argument('--apply', action='store_true',
                   help='Применить (без флага — dry-run)')
    p.add_argument('--delete-src', action='store_true',
                   help='Удалить src юзера после мержа (только с --apply)')
    return p.parse_args()


def _print_pair(label: str, u) -> None:
    print(f'  {label}: id={u.id}  email={u.email}  name={u.full_name}  '
          f'is_owner={u.is_owner}', flush=True)


def _table_exists(name: str) -> bool:
    r = db.session.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {'t': name}).fetchone()
    return bool(r)


def _column_exists(table: str, col: str) -> bool:
    r = db.session.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {'t': table, 'c': col}).fetchone()
    return bool(r)


def _count(sql: str, params: dict) -> int:
    r = db.session.execute(text(sql), params)
    return int(r.scalar() or 0)


def main() -> int:
    args = _parse_args()

    if args.delete_src and not args.apply:
        print('--delete-src требует --apply', flush=True)
        return 2

    with app.app_context():
        src_row = db.session.execute(text(
            "SELECT id, email, full_name, is_owner FROM system_users WHERE email = :e"
        ), {'e': args.src.strip()}).fetchone()
        dst_row = db.session.execute(text(
            "SELECT id, email, full_name, is_owner FROM system_users WHERE email = :e"
        ), {'e': args.dst.strip()}).fetchone()

        if not src_row:
            print(f'SRC не найден: {args.src}', flush=True)
            return 1
        if not dst_row:
            print(f'DST не найден: {args.dst}', flush=True)
            return 1
        if src_row.id == dst_row.id:
            print('src == dst, нечего делать', flush=True)
            return 0

        print('=== Merge system_users ===', flush=True)
        print(f'  SRC: id={src_row.id} email={src_row.email} '
              f'name={src_row.full_name} is_owner={src_row.is_owner}',
              flush=True)
        print(f'  DST: id={dst_row.id} email={dst_row.email} '
              f'name={dst_row.full_name} is_owner={dst_row.is_owner}',
              flush=True)
        print(f'  MODE: {"APPLY" if args.apply else "DRY-RUN"}'
              f'  delete_src={args.delete_src}', flush=True)
        print('', flush=True)

        if src_row.is_owner:
            print('⚠️  SRC помечен is_owner=True — отказываюсь мержить, сначала '
                  'сними флаг владельца. Прервано.', flush=True)
            return 1

        src_id, dst_id = int(src_row.id), int(dst_row.id)
        total_upd = 0
        total_del = 0

        # 1. UNIQUE-tables: сначала DELETE src-дублей, затем UPDATE оставшихся
        print('--- UNIQUE constraints (сначала DELETE конфликтов) ---',
              flush=True)
        for tbl, col, other in UNIQUE_TABLES:
            if not _table_exists(tbl):
                print(f'  skip  {tbl}: таблицы нет', flush=True)
                continue
            if not _column_exists(tbl, col):
                print(f'  skip  {tbl}.{col}: колонки нет', flush=True)
                continue

            if other:
                where = ' AND '.join([f't.{o} = s.{o}' for o in other])
                del_sql = (
                    f"DELETE FROM {tbl} s "
                    f"WHERE s.{col} = :src "
                    f"  AND EXISTS (SELECT 1 FROM {tbl} t "
                    f"              WHERE t.{col} = :dst AND {where})"
                )
                count_sql = (
                    f"SELECT COUNT(*) FROM {tbl} s "
                    f"WHERE s.{col} = :src "
                    f"  AND EXISTS (SELECT 1 FROM {tbl} t "
                    f"              WHERE t.{col} = :dst AND {where})"
                )
            else:
                del_sql = f"DELETE FROM {tbl} WHERE {col} = :src"
                count_sql = f"SELECT COUNT(*) FROM {tbl} WHERE {col} = :src"

            if args.apply:
                r = db.session.execute(text(del_sql),
                                       {'src': src_id, 'dst': dst_id})
                print(f'  DEL  {tbl:28s} .{col}: {r.rowcount}', flush=True)
                total_del += r.rowcount
            else:
                cnt = _count(count_sql, {'src': src_id, 'dst': dst_id})
                print(f'  would DEL  {tbl:28s} .{col}: {cnt}', flush=True)

            upd_sql = f"UPDATE {tbl} SET {col} = :dst WHERE {col} = :src"
            cnt_sql = f"SELECT COUNT(*) FROM {tbl} WHERE {col} = :src"
            if args.apply:
                r = db.session.execute(text(upd_sql),
                                       {'src': src_id, 'dst': dst_id})
                print(f'  UPD  {tbl:28s} .{col}: {r.rowcount}', flush=True)
                total_upd += r.rowcount
            else:
                cnt = _count(cnt_sql, {'src': src_id})
                print(f'  would UPD  {tbl:28s} .{col}: {cnt}', flush=True)

        # 2. Простые UPDATE'ы
        print('', flush=True)
        print('--- PLAIN updates ---', flush=True)
        for tbl, col in PLAIN_UPDATES:
            if not _table_exists(tbl):
                print(f'  skip  {tbl}: таблицы нет', flush=True)
                continue
            if not _column_exists(tbl, col):
                print(f'  skip  {tbl}.{col}: колонки нет', flush=True)
                continue

            upd_sql = f"UPDATE {tbl} SET {col} = :dst WHERE {col} = :src"
            cnt_sql = f"SELECT COUNT(*) FROM {tbl} WHERE {col} = :src"
            if args.apply:
                r = db.session.execute(text(upd_sql),
                                       {'src': src_id, 'dst': dst_id})
                print(f'  UPD  {tbl:28s} .{col}: {r.rowcount}', flush=True)
                total_upd += r.rowcount
            else:
                cnt = _count(cnt_sql, {'src': src_id})
                print(f'  would UPD  {tbl:28s} .{col}: {cnt}', flush=True)

        # 3. kp_history (без FK, фильтруем по user_role='admin')
        if _table_exists('kp_history'):
            if args.apply:
                r = db.session.execute(text(KP_HISTORY_UPDATE),
                                       {'src': src_id, 'dst': dst_id})
                print(f'  UPD  kp_history (role=admin): {r.rowcount}',
                      flush=True)
                total_upd += r.rowcount
            else:
                cnt = _count(KP_HISTORY_COUNT, {'src': src_id})
                print(f'  would UPD  kp_history (role=admin): {cnt}',
                      flush=True)

        # 4. Alias + опционально удаление src
        print('', flush=True)
        if args.apply:
            if _table_exists('system_user_email_alias'):
                db.session.execute(text(
                    "INSERT INTO system_user_email_alias (email, user_id, note) "
                    "VALUES (:em, :uid, :note) "
                    "ON CONFLICT (email) DO UPDATE "
                    "SET user_id = EXCLUDED.user_id, note = EXCLUDED.note"
                ), {
                    'em': src_row.email,
                    'uid': dst_id,
                    'note': (f'merged from id={src_id} ({src_row.full_name}) '
                             f'→ id={dst_id} at '
                             f'{datetime.utcnow().isoformat()}Z'),
                })
                print(f'  ALIAS: {src_row.email} → user#{dst_id}', flush=True)
            else:
                print('  ⚠️  system_user_email_alias не существует — '
                      'запусти apply_system_user_email_alias.py', flush=True)

            if args.delete_src:
                db.session.execute(text(
                    "DELETE FROM system_users WHERE id = :id"
                ), {'id': src_id})
                print(f'  DELETED user id={src_id}', flush=True)

            db.session.commit()
            print('', flush=True)
            print(f'COMMITTED. updates={total_upd}  '
                  f'deleted_conflicts={total_del}', flush=True)
        else:
            print('DRY-RUN — ничего не записано. Запусти с --apply '
                  '(и --delete-src чтобы удалить src юзера).', flush=True)

    return 0


if __name__ == '__main__':
    sys.exit(main())
