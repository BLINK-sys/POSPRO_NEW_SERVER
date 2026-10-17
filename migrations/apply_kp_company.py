"""
Миграция: таблица kp_company + deal_contact + колонки company_id в
kp_client и deal.

Запуск через Render Job:
    python -u -m migrations.apply_kp_company
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_kp_company.sql')


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: kp_company + deal_contact', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    checks = [
        ("kp_company table",
         "SELECT 1 FROM information_schema.tables WHERE table_name='kp_company'"),
        ("deal_contact table",
         "SELECT 1 FROM information_schema.tables WHERE table_name='deal_contact'"),
        ("kp_client.company_id",
         "SELECT 1 FROM information_schema.columns "
         "WHERE table_name='kp_client' AND column_name='company_id'"),
        ("deal.company_id",
         "SELECT 1 FROM information_schema.columns "
         "WHERE table_name='deal' AND column_name='company_id'"),
    ]
    for label, q in checks:
        row = db.session.execute(text(q)).fetchone()
        print(f"  {'OK' if row else 'MISSING'}: {label}", flush=True)

    # Статистика бэкфила: сколько deal_contact создано.
    cnt = db.session.execute(text("SELECT COUNT(*) FROM deal_contact")).scalar()
    print(f"  deal_contact rows after backfill: {cnt}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
