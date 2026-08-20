"""
Миграция: создать таблицы section_cards и section_card_categories.

Идемпотентно (CREATE TABLE IF NOT EXISTS).

Запуск:
    python -u -m migrations.apply_section_cards
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_section_cards.sql')


def _split_statements(sql: str):
    # Простой сплит по ; на верхнем уровне (в этом файле нет DO $$).
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: add_section_cards', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    for tbl in ('section_cards', 'section_card_categories'):
        row = db.session.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = :t"
        ), {'t': tbl}).first()
        print(f'  {tbl}: {"OK" if row else "MISSING"}', flush=True)
    print('Done', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
