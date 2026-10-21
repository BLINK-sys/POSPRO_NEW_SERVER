"""
Разово: всем пометить все чаты прочитанными + все уведомления прочитанными.
После массового импорта чатов из B24 у менеджеров 99+ непрочитанных —
это шум, их никто не писал сам.

Что делает:
  1. UPDATE chat_member SET last_read_at = NOW() WHERE last_read_at IS NULL
     OR last_read_at < NOW()
  2. UPDATE notification SET read_at = NOW() WHERE read_at IS NULL

Dry-run по умолчанию. --apply для реального.
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
    p.add_argument('--apply', action='store_true')
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    with app.app_context():
        print(f'mode={"APPLY" if args.apply else "DRY-RUN"}', flush=True)

        # 1. chat_member.last_read_at → NOW() (считай всё прочитанным)
        n_unread_members = db.session.execute(text("""
            SELECT COUNT(*) FROM chat_member
             WHERE last_read_at IS NULL OR last_read_at < NOW()
        """)).scalar()
        total_members = db.session.execute(text(
            "SELECT COUNT(*) FROM chat_member"
        )).scalar()
        print(f'\n=== chat_member ===', flush=True)
        print(f'  всего:                    {total_members}', flush=True)
        print(f'  с устаревшим last_read_at: {n_unread_members}', flush=True)
        if args.apply:
            r = db.session.execute(text("""
                UPDATE chat_member
                   SET last_read_at = NOW()
                 WHERE last_read_at IS NULL OR last_read_at < NOW()
            """))
            db.session.commit()
            print(f'  обновлено:                 {r.rowcount}', flush=True)

        # 2. notification.read_at IS NULL → NOW()
        n_unread_notif = db.session.execute(text(
            "SELECT COUNT(*) FROM notification WHERE read_at IS NULL"
        )).scalar()
        total_notif = db.session.execute(text(
            "SELECT COUNT(*) FROM notification"
        )).scalar()
        print(f'\n=== notification ===', flush=True)
        print(f'  всего:                    {total_notif}', flush=True)
        print(f'  непрочитанных:            {n_unread_notif}', flush=True)
        if args.apply:
            r = db.session.execute(text("""
                UPDATE notification
                   SET read_at = NOW()
                 WHERE read_at IS NULL
            """))
            db.session.commit()
            print(f'  помечено прочитанными:    {r.rowcount}', flush=True)

        if not args.apply:
            print('\nDRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
