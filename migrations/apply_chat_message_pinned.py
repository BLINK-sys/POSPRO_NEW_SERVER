"""
Миграция: chat_message.pinned_at + pinned_by.

Запуск разово через Render Job:
    python -u -m migrations.apply_chat_message_pinned
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_chat_message_pinned.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: chat_message.pinned_at + pinned_by', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    for col in ('pinned_at', 'pinned_by'):
        row = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = 'chat_message' AND column_name = '{col}'"
        )).fetchone()
        print(f"  {'OK' if row else 'MISSING'}: chat_message.{col}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
