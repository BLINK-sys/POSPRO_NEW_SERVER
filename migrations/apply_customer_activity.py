"""
Миграция: создать таблицу customer_activity_events + индексы.

Идемпотентно (CREATE TABLE / INDEX IF NOT EXISTS).

Запуск:
    python -u -m migrations.apply_customer_activity
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_customer_activity.sql')


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: add_customer_activity', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name = 'customer_activity_events'"
    )).first()
    print(f'  customer_activity_events: {"OK" if row else "MISSING"}', flush=True)
    print('Done', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
