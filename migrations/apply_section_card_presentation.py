"""
Миграция: добавить поле presentation_pdf_url в section_cards.

Идемпотентно (ADD COLUMN IF NOT EXISTS).

Запуск:
    python -u -m migrations.apply_section_card_presentation
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_section_card_presentation.sql')


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: add_section_card_presentation', flush=True)
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            db.session.execute(text(s))
    db.session.commit()

    row = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='section_cards' AND column_name='presentation_pdf_url'"
    )).first()
    print(f'  section_cards.presentation_pdf_url: {"OK" if row else "MISSING"}', flush=True)
    print('Done', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
