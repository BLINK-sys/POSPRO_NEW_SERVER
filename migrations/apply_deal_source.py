"""
Миграция: таблица deal_source + deal.source_id + crm_ingest_source.default_deal_source_id.
Старые deal.source (enum) обнуляются.

Запуск:
    python -u -m migrations.apply_deal_source
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_deal_source.sql')


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: deal_source + FK fields', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    for check in (
        ("table", "deal_source"),
        ("column", "deal.source_id"),
        ("column", "crm_ingest_source.default_deal_source_id"),
    ):
        kind, path = check
        if kind == 'table':
            r = db.session.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_name = :t"
            ), {'t': path}).fetchone()
        else:
            tbl, col = path.split('.')
            r = db.session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ), {'t': tbl, 'c': col}).fetchone()
        print(f"  {'OK' if r else 'MISSING'}: {path}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
