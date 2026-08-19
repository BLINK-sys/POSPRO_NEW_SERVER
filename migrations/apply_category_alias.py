"""
Разовая миграция: создать таблицу category_alias для системы алиасов
категорий (см. `services/category_resolver.py` и модель
`models/category_alias.py`).

Идемпотентна: `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.
Отдельно от normalize_categories — сначала таблица, потом (по желанию)
нормализация имён и seed-алиасы.

Запуск (Render Shell или локально):
    cd pospro_new_server
    python -u -m migrations.apply_category_alias
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'create_category_alias.sql')


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

    print(f'Statements to execute: {len(statements)}', flush=True)
    for i, stmt in enumerate(statements, 1):
        first_line = stmt.splitlines()[0][:80]
        print(f'  [{i:>2}/{len(statements)}] {first_line}...', flush=True)
        db.session.execute(text(stmt))

    db.session.commit()

    count = db.session.execute(text('SELECT COUNT(*) FROM category_alias')).scalar()
    print(f'  category_alias: {count} rows', flush=True)
    print('OK', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
