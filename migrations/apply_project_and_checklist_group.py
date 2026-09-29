"""
Миграция: справочник Project + task.project_id + task_checklist.group_name.

Идемпотентно.

Запуск:
    python -u -m migrations.apply_project_and_checklist_group
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_project_and_checklist_group.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: add_project_and_checklist_group', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    checks = [
        ("project", "SELECT to_regclass('project')"),
        ("task.project_id",
         "SELECT column_name FROM information_schema.columns "
         "WHERE table_name = 'task' AND column_name = 'project_id'"),
        ("task_checklist.group_name",
         "SELECT column_name FROM information_schema.columns "
         "WHERE table_name = 'task_checklist' AND column_name = 'group_name'"),
    ]
    for label, q in checks:
        row = db.session.execute(text(q)).fetchone()
        ok = row is not None and row[0] is not None
        print(f"  {'✓' if ok else '✗'} {label}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
