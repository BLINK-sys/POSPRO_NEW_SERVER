"""
Миграция: добавить brands_cards_per_row в homepage_blocks.

Запуск:
    python -u -m migrations.apply_brands_cards_per_row
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_brands_cards_per_row.sql')


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()
    print('Applying: add_brands_cards_per_row', flush=True)
    for s in (stmt.strip() for stmt in sql.split(';')):
        if s:
            db.session.execute(text(s))
    db.session.commit()
    row = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='homepage_blocks' AND column_name='brands_cards_per_row'"
    )).first()
    print(f'  homepage_blocks.brands_cards_per_row: {"OK" if row else "MISSING"}', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
