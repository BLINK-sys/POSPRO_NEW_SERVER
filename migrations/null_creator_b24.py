"""
Обнуление created_by у клиентов (kp_client) или компаний (kp_company),
импортированных из B24, где текущий creator = owner (fallback из миграции).

В B24 у этих записей фактически не было явного ASSIGNED_BY_ID (либо юзер
не был замаплен в system_users) — импорт поставил owner чтобы не упасть.
Правильное состояние — NULL (на UI показывается как «Без создателя»).

Фильтруем ТОЛЬКО записи из b24_mirror — не трогаем то что было создано
вручную через UI на том же юзере.

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.null_creator_b24 --entity client  --user bocan.anton@mail.ru
    python -u -m migrations.null_creator_b24 --entity company --user bocan.anton@mail.ru --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


# entity → (table, b24_mirror.entity_type)
ENTITY_MAP = {
    'client':  ('kp_client',  'contact'),
    'company': ('kp_company', 'company'),
}


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--entity', required=True, choices=sorted(ENTITY_MAP.keys()),
                   help='Что чистим: client или company')
    p.add_argument('--user', required=True,
                   help='Email юзера-фоллбека (чьи записи «размаппить»)')
    p.add_argument('--apply', action='store_true',
                   help='Применить (без флага — dry-run)')
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    table, mirror_type = ENTITY_MAP[args.entity]

    with app.app_context():
        u = db.session.execute(text(
            "SELECT id, email, full_name FROM system_users WHERE email = :e"
        ), {'e': args.user.strip()}).fetchone()
        if not u:
            print(f'Юзер не найден: {args.user}', flush=True)
            return 1

        print('=== Null created_by on B24-imported ===', flush=True)
        print(f'  ENTITY: {args.entity} ({table}, b24_mirror.entity_type={mirror_type!r})',
              flush=True)
        print(f'  USER (fallback owner): id={u.id} email={u.email} '
              f'name={u.full_name}', flush=True)
        print(f'  MODE: {"APPLY" if args.apply else "DRY-RUN"}', flush=True)
        print('', flush=True)

        b24_subq = (
            f"SELECT pospro_id FROM b24_mirror "
            f"WHERE entity_type = '{mirror_type}'"
        )

        cnt = db.session.execute(text(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE created_by = :uid "
            f"  AND id IN ({b24_subq})"
        ), {'uid': u.id}).scalar() or 0

        total_on_user = db.session.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE created_by = :uid"
        ), {'uid': u.id}).scalar() or 0

        print(f'B24-записи где created_by={u.id}: {cnt}', flush=True)
        print(f'  (всего на юзере created_by={total_on_user} — '
              f'остаток после обнуления = {total_on_user - cnt})', flush=True)

        if cnt == 0:
            print('Нечего делать.', flush=True)
            return 0

        if not args.apply:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
            return 0

        print('', flush=True)
        print('APPLYing…', flush=True)
        r = db.session.execute(text(
            f"UPDATE {table} SET created_by = NULL "
            f"WHERE created_by = :uid "
            f"  AND id IN ({b24_subq})"
        ), {'uid': u.id})
        db.session.commit()
        print(f'  UPD created_by → NULL: {r.rowcount}', flush=True)
        print('COMMITTED.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
