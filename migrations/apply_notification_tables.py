"""
Разовая миграция для Этапа 6: notification + web_push_subscription +
user_presence.

Плюс тот же трюк с `ALTER TABLE ... ALTER COLUMN ... SET DEFAULT
CURRENT_TIMESTAMP` — на случай если `db.create_all()` уже успел создать
таблицы через SQLAlchemy без DB-level дефолтов (Python-side `default=`
не даёт server-default, см. историю в apply_crm_tables.py).

Запуск:
    python -u -m migrations.apply_notification_tables
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'create_notification_tables.sql')

TABLES = ['notification', 'web_push_subscription', 'user_presence']

_TIMESTAMP_DEFAULTS = [
    ('notification',           ('created_at',)),
    ('web_push_subscription',  ('created_at',)),
    ('user_presence',          ('last_heartbeat_at',)),
]


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()
    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]
    print(f'Statements to execute: {len(statements)}', flush=True)
    for i, stmt in enumerate(statements, 1):
        first = stmt.splitlines()[0][:80]
        print(f'  [{i:>2}/{len(statements)}] {first}...', flush=True)
        db.session.execute(text(stmt))
    db.session.commit()

    print('', flush=True)
    print('=== Ensure timestamp DEFAULTs ===', flush=True)
    for tbl, cols in _TIMESTAMP_DEFAULTS:
        for col in cols:
            db.session.execute(text(
                f'ALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT CURRENT_TIMESTAMP'
            ))
        print(f'  {tbl}: {", ".join(cols)} → DEFAULT CURRENT_TIMESTAMP', flush=True)
    db.session.commit()

    print('', flush=True)
    print('=== Tables ===', flush=True)
    for tbl in TABLES:
        count = db.session.execute(text(f'SELECT COUNT(*) FROM {tbl}')).scalar()
        print(f'  {tbl:<24} {count:>6} rows', flush=True)
    print('OK', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
