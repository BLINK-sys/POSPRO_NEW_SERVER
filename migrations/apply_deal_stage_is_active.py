"""
Миграция: DealStage.is_active (деактивация стадий без удаления).

Запуск:  python -u -m migrations.apply_deal_stage_is_active
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_deal_stage_is_active.sql')


def _split(sql: str):
    for s in sql.split(';'):
        s = s.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()
    print('Applying migration: deal_stage.is_active', flush=True)
    for stmt in _split(sql):
        db.session.execute(text(stmt))
    db.session.commit()
    row = db.session.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='deal_stage' AND column_name='is_active'"
    )).fetchone()
    print(f"  {'OK' if row else 'MISSING'}: deal_stage.is_active", flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
