"""
Миграция: deal_source_variant + deal.source_variant_id.

Запуск через Render Job:
    python -u -m migrations.apply_deal_source_variant
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_deal_source_variant.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: deal_source_variant', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    rows = db.session.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'deal_source_variant'"
    )).fetchone()
    print(f"  {'OK' if rows else 'MISSING'}: deal_source_variant", flush=True)

    rows = db.session.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='deal' AND column_name='source_variant_id'"
    )).fetchone()
    print(f"  {'OK' if rows else 'MISSING'}: deal.source_variant_id", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
