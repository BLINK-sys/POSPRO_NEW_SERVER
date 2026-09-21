"""
Миграция: deal.creator_id + entity_attachment.title.

Идемпотентно — все ALTER'ы под IF NOT EXISTS.

Запуск:
    python -u -m migrations.apply_deal_creator_and_attachment_title
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'add_deal_creator_and_attachment_title.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    print('Applying migration: add_deal_creator_and_attachment_title', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    # Проверка.
    row = db.session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'deal' AND column_name = 'creator_id'
    """)).fetchone()
    if row:
        print("  ✓ deal.creator_id present", flush=True)
    else:
        print("  ✗ deal.creator_id MISSING", flush=True)

    row = db.session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'entity_attachment' AND column_name = 'title'
    """)).fetchone()
    if row:
        print("  ✓ entity_attachment.title present", flush=True)
    else:
        print("  ✗ entity_attachment.title MISSING", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
