"""
Миграция: task_watcher (per-user «избранные» задачи).

Запуск через Render Job:
    python -u -m migrations.apply_task_watcher
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_task_watcher.sql')


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: task_watcher', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'task_watcher'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: task_watcher table", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
