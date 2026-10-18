"""
Обнуление responsible_user_id у сделок, пришедших из B24, где текущий
responsible = owner (fallback из миграции). В B24 у этих сделок фактически
не было ответственного — импорт поставил owner'а чтобы не упасть на FK,
но реальной привязки нет. Правильное состояние — NULL.

Фильтруем ТОЛЬКО сделки из b24_mirror (чтобы не обнулить реальные сделки
созданные самим юзером через UI, где он сам ответственный).

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.null_responsible_b24 --user bocan.anton@mail.ru
    python -u -m migrations.null_responsible_b24 --user bocan.anton@mail.ru --apply
    # Также обнулить creator_id у тех же сделок:
    python -u -m migrations.null_responsible_b24 --user bocan.anton@mail.ru --apply --null-creator
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
                   help='Email юзера-фоллбека (чьи сделки «размаппить»)')
    p.add_argument('--apply', action='store_true',
                   help='Применить (без флага — dry-run)')
    p.add_argument('--null-creator', action='store_true',
                   help='Обнулить также creator_id (не только responsible)')
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    with app.app_context():
        u = db.session.execute(text(
            "SELECT id, email, full_name FROM system_users WHERE email = :e"
        ), {'e': args.user.strip()}).fetchone()
        if not u:
            print(f'Юзер не найден: {args.user}', flush=True)
            return 1

        print('=== Null responsible on B24-imported deals ===', flush=True)
        print(f'  USER (fallback owner): id={u.id} email={u.email} '
              f'name={u.full_name}', flush=True)
        print(f'  MODE: {"APPLY" if args.apply else "DRY-RUN"}  '
              f'null_creator={args.null_creator}', flush=True)
        print('', flush=True)

        # Common WHERE: сделки из b24_mirror
        b24_subq = ("SELECT pospro_id FROM b24_mirror "
                    "WHERE entity_type = 'deal'")

        # 1) responsible = user AND из b24_mirror
        cnt_resp = db.session.execute(text(
            f"SELECT COUNT(*) FROM deal "
            f"WHERE responsible_user_id = :uid "
            f"  AND id IN ({b24_subq})"
        ), {'uid': u.id}).scalar() or 0

        cnt_creator = db.session.execute(text(
            f"SELECT COUNT(*) FROM deal "
            f"WHERE creator_id = :uid "
            f"  AND id IN ({b24_subq})"
        ), {'uid': u.id}).scalar() or 0

        print(f'B24-сделки где responsible={u.id}: {cnt_resp}', flush=True)
        print(f'B24-сделки где creator={u.id}:     {cnt_creator}', flush=True)

        # Для сравнения — сколько сделок всего на юзере (включая не из B24)
        total_resp = db.session.execute(text(
            "SELECT COUNT(*) FROM deal WHERE responsible_user_id = :uid"
        ), {'uid': u.id}).scalar() or 0
        total_creator = db.session.execute(text(
            "SELECT COUNT(*) FROM deal WHERE creator_id = :uid"
        ), {'uid': u.id}).scalar() or 0
        print(f'  (всего на юзере responsible={total_resp}, '
              f'creator={total_creator} — остаток после обнуления = НЕ-B24 сделки)',
              flush=True)

        if cnt_resp == 0 and (not args.null_creator or cnt_creator == 0):
            print('Нечего делать.', flush=True)
            return 0

        if not args.apply:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
            return 0

        print('', flush=True)
        print('APPLYing…', flush=True)

        r1 = db.session.execute(text(
            f"UPDATE deal SET responsible_user_id = NULL "
            f"WHERE responsible_user_id = :uid "
            f"  AND id IN ({b24_subq})"
        ), {'uid': u.id})
        print(f'  UPD responsible → NULL: {r1.rowcount}', flush=True)

        if args.null_creator:
            r2 = db.session.execute(text(
                f"UPDATE deal SET creator_id = NULL "
                f"WHERE creator_id = :uid "
                f"  AND id IN ({b24_subq})"
            ), {'uid': u.id})
            print(f'  UPD creator → NULL:     {r2.rowcount}', flush=True)

        db.session.commit()
        print('', flush=True)
        print('COMMITTED.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
