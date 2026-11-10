"""
Миграция: таблица entity_attachment_version для истории файловых
правок из встроенного редактора. Идемпотентно (IF NOT EXISTS).

Запуск через Render Job:
    python -u -m migrations.apply_entity_attachment_version
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_entity_attachment_version.sql')


def _split_statements(sql: str):
    """Тот же защитный splitter что в apply_project_member_settings:
    пропускаем chunks где все не-пустые строки — комментарии (`--`)."""
    for stmt in sql.split(';'):
        s = stmt.strip()
        if not s:
            continue
        non_comment = [
            ln for ln in s.splitlines()
            if ln.strip() and not ln.strip().startswith('--')
        ]
        if not non_comment:
            continue
        yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()
    print('Applying migration: entity_attachment_version', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {'t': 'entity_attachment_version'}).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: entity_attachment_version", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
