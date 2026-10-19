"""
Миграция: dictionary + dictionary_item + deal_stage.required_dict_codes +
deal.survey_values.

Запуск через Render Job:
    python -u -m migrations.apply_dictionary
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_dictionary.sql')


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: dictionary + deal_stage.required_dict_codes + deal.survey_values',
          flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    checks = [
        ("SELECT 1 FROM information_schema.tables WHERE table_name='dictionary'",
         'dictionary table'),
        ("SELECT 1 FROM information_schema.tables WHERE table_name='dictionary_item'",
         'dictionary_item table'),
        ("SELECT 1 FROM information_schema.columns WHERE table_name='deal_stage' AND column_name='required_dict_codes'",
         'deal_stage.required_dict_codes'),
        ("SELECT 1 FROM information_schema.columns WHERE table_name='deal' AND column_name='survey_values'",
         'deal.survey_values'),
    ]
    for sql_q, label in checks:
        row = db.session.execute(text(sql_q)).fetchone()
        print(f"  {'OK' if row else 'MISSING'}: {label}", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
