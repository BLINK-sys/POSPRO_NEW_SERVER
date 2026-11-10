"""
Миграция: таблица project_member_settings.

Хранит per-user настройку «видит все задачи проекта / только свои».
Полноценное «членство» в проекте теперь computed из задач.

Идемпотентно. Запуск через Render Job:
    python -u -m migrations.apply_project_member_settings
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_project_member_settings.sql')


def _split_statements(sql: str):
    """
    Наивный splitter по ';' — осторожно с ';' в комментариях. Чтобы
    не падать «can't execute an empty query», отфильтровываем куски,
    в которых все непустые строки — комментарии (`--`).
    """
    for stmt in sql.split(';'):
        s = stmt.strip()
        if not s:
            continue
        # все непустые строки = комментарии → это pure-comment chunk,
        # который psycopg2 не умеет выполнять. Пропускаем.
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

    print('Applying migration: project_member_settings', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {'t': 'project_member_settings'}).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: project_member_settings", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
