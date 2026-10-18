"""
Миграция: таблица user_preferences (per-user UI state).

Запуск:  python -u -m migrations.apply_user_preferences
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_user_preferences.sql')


def _split(sql: str):
    for s in sql.split(';'):
        s = s.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()
    print('Applying migration: user_preferences', flush=True)
    for stmt in _split(sql):
        db.session.execute(text(stmt))
    db.session.commit()
    row = db.session.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name='user_preferences'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: user_preferences", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
