"""
Миграция таблиц уведомлений: notification, web_push_subscription, user_presence.

SQL идемпотентная (CREATE TABLE IF NOT EXISTS), безопасно гнать
повторно.

Запуск:
    python -u -m migrations.apply_notifications
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'create_notification_tables.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: notification / web_push_subscription / user_presence', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    for tbl in ('notification', 'web_push_subscription', 'user_presence'):
        row = db.session.execute(text(
            "SELECT 1 FROM information_schema.tables "
            f"WHERE table_name = '{tbl}'"
        )).fetchone()
        print(f"  {'OK' if row else 'MISSING'}: {tbl}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
