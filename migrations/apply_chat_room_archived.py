"""
Миграция: chat_room.is_archived + archived_at + чистка orphan-чатов.

Идемпотентная. Запуск разово через Render Job:
    python -u -m migrations.apply_chat_room_archived
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_chat_room_archived.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: chat_room archived + orphan cleanup', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'chat_room' AND column_name = 'is_archived'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: chat_room.is_archived", flush=True)

    row = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'chat_room' AND column_name = 'archived_at'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: chat_room.archived_at", flush=True)

    # Диагностика: сколько чатов теперь в архиве.
    cnt = db.session.execute(text(
        "SELECT COUNT(*) FROM chat_room WHERE is_archived = TRUE"
    )).scalar()
    print(f"  archived rooms: {cnt}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
