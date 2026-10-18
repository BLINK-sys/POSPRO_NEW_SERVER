"""
Удаление всех сделок, где заданный юзер является creator ИЛИ
responsible_user_id. По умолчанию dry-run — только печатает count и
sample. С `--apply` удаляет (CASCADE снесёт deal_member, deal_activity,
deal_kp, chat_room(deal) с пустыми чатами и т.д.).

ОСТОРОЖНО: это массовое удаление. Запускать строго с явным
подтверждением пользователя.

Запуск через Render Job:
    python -u -m migrations.delete_user_deals --user bocan.anton@mail.ru
    python -u -m migrations.delete_user_deals --user bocan.anton@mail.ru --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user', required=True,
                   help='Email юзера чьи сделки удалить')
    p.add_argument('--apply', action='store_true',
                   help='Удалить (без флага — dry-run)')
    p.add_argument('--sample', type=int, default=20,
                   help='Сколько имён показать в sample (default 20)')
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    with app.app_context():
        u = db.session.execute(text(
            "SELECT id, email, full_name, is_owner "
            "FROM system_users WHERE email = :e"
        ), {'e': args.user.strip()}).fetchone()
        if not u:
            print(f'Юзер не найден: {args.user}', flush=True)
            return 1

        print('=== Delete deals by user ===', flush=True)
        print(f'  USER: id={u.id} email={u.email} name={u.full_name} '
              f'is_owner={u.is_owner}', flush=True)
        print(f'  MODE: {"APPLY (REAL DELETE)" if args.apply else "DRY-RUN"}',
              flush=True)
        print('', flush=True)

        # Сначала найдём все id сделок (responsible OR creator) — один раз.
        ids = [r[0] for r in db.session.execute(text(
            "SELECT id FROM deal "
            "WHERE responsible_user_id = :uid OR creator_id = :uid "
            "ORDER BY id"
        ), {'uid': u.id}).fetchall()]

        total = len(ids)
        print(f'Найдено сделок: {total}', flush=True)
        if total == 0:
            print('Нечего удалять.', flush=True)
            return 0

        # Разбивка по роли + статусу — чтобы юзер видел картину.
        resp_cnt = db.session.execute(text(
            "SELECT COUNT(*) FROM deal WHERE responsible_user_id = :uid"
        ), {'uid': u.id}).scalar() or 0
        creat_cnt = db.session.execute(text(
            "SELECT COUNT(*) FROM deal WHERE creator_id = :uid"
        ), {'uid': u.id}).scalar() or 0
        both_cnt = db.session.execute(text(
            "SELECT COUNT(*) FROM deal "
            "WHERE responsible_user_id = :uid AND creator_id = :uid"
        ), {'uid': u.id}).scalar() or 0
        print(f'  responsible_user_id={u.id}: {resp_cnt}', flush=True)
        print(f'  creator_id={u.id}:         {creat_cnt}', flush=True)
        print(f'  обе роли сразу:            {both_cnt}', flush=True)

        by_status = db.session.execute(text(
            "SELECT status, COUNT(*) FROM deal "
            "WHERE responsible_user_id = :uid OR creator_id = :uid "
            "GROUP BY status ORDER BY status"
        ), {'uid': u.id}).fetchall()
        print('  по статусу:', flush=True)
        for st, c in by_status:
            print(f'     {st:10s} {c}', flush=True)

        # Sample для глаза — покажем N первых по дате убывания.
        print('', flush=True)
        print(f'Sample (последние {args.sample}):', flush=True)
        sample_rows = db.session.execute(text(
            "SELECT id, name, status, created_at, amount, currency "
            "FROM deal "
            "WHERE responsible_user_id = :uid OR creator_id = :uid "
            "ORDER BY created_at DESC LIMIT :lim"
        ), {'uid': u.id, 'lim': args.sample}).fetchall()
        for r in sample_rows:
            created = r.created_at.strftime('%Y-%m-%d') if r.created_at else '—'
            amt = f'{r.amount}' if r.amount is not None else '—'
            name = (r.name or '')[:60]
            print(f'  #{r.id:<6} [{r.status}] {created} {amt} {r.currency or ""}  {name}',
                  flush=True)

        print('', flush=True)
        if not args.apply:
            print(f'DRY-RUN — ничего не удалено. '
                  f'Для реального удаления: --apply', flush=True)
            return 0

        # APPLY: удаляем по кускам (защита от огромной транзакции на огромных N).
        # Deal.cascade удалит DealMember, DealActivity, DealKp, DealOrder,
        # DealContact, Chat_room (где related_deal_id не NULL и чат пустой)
        # — автоматически через ondelete=CASCADE в моделях.
        print('APPLYing — удаляю…', flush=True)
        batch_size = 200
        deleted = 0
        for i in range(0, total, batch_size):
            batch = ids[i:i + batch_size]
            r = db.session.execute(text(
                "DELETE FROM deal WHERE id = ANY(:ids)"
            ), {'ids': batch})
            db.session.commit()
            deleted += r.rowcount
            print(f'  batch {i // batch_size + 1}: удалено {r.rowcount} '
                  f'(всего {deleted}/{total})', flush=True)

        print('', flush=True)
        print(f'COMMITTED. deleted={deleted}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
