"""
Миграция: расширяем footer_settings юр.реквизитами + полями
contacts_order / info_order для сортировки элементов в подвале.

Идемпотентно (ADD COLUMN IF NOT EXISTS). Запуск через Render Job:
    python -u -m migrations.apply_footer_requisites
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_footer_requisites.sql')


def _split_statements(sql: str):
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


_EXPECTED_COLUMNS = (
    'legal_name', 'bin_number', 'legal_address',
    'bank_name', 'bank_bic', 'bank_iik', 'bank_kbe',
    'contacts_order', 'info_order',
)


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: footer_requisites', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    rows = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'footer_settings' AND column_name = ANY(:cols)"
    ), {'cols': list(_EXPECTED_COLUMNS)}).fetchall()
    present = {r[0] for r in rows}
    for col in _EXPECTED_COLUMNS:
        print(f"  {'OK' if col in present else 'MISSING'}: footer_settings.{col}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
