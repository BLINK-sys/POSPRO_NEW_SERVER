"""
Миграция: task_checklist.depends_on_group.

Запуск:
    python -u -m migrations.apply_checklist_depends_on
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_checklist_depends_on.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: add_checklist_depends_on', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'task_checklist' AND column_name = 'depends_on_group'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: task_checklist.depends_on_group", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
