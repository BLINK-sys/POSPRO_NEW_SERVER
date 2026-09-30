"""
Миграция: system_users.can_manage_projects.

Запуск через Render Job:
    python -u -m migrations.apply_system_users_can_manage_projects
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_system_users_can_manage_projects.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: system_users.can_manage_projects', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'system_users' AND column_name = 'can_manage_projects'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: system_users.can_manage_projects", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
