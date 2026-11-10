"""
Миграция: модуль «Проекты» с канбаном.

Создаёт project_member / project_stage, расширяет Project / Task /
ChatRoom. Идемпотентно через IF NOT EXISTS.

Запуск через Render Job:
    python -u -m migrations.apply_projects_kanban
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_projects_kanban.sql')


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: projects kanban', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    for table in ('project_member', 'project_stage'):
        row = db.session.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ), {'t': table}).fetchone()
        print(f"  {'OK' if row else 'MISSING'}: {table}", flush=True)

    # Проверяем добавленные колонки.
    for tbl, col in [
        ('project', 'status'),
        ('project', 'owner_id'),
        ('task', 'project_stage_id'),
        ('task', 'prev_project_stage_id'),
        ('chat_room', 'related_project_id'),
    ]:
        row = db.session.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ), {'t': tbl, 'c': col}).fetchone()
        print(f"  {'OK' if row else 'MISSING'}: {tbl}.{col}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
