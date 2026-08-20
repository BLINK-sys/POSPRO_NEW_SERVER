"""
Разовая миграция: добавить в homepage_blocks поля для кастомизации блока
товаров — `background_color` (VARCHAR 9) и `show_products_categories_filter`
(BOOLEAN NOT NULL DEFAULT TRUE).

Идемпотентно: колонки создаются через DO $$ / IF NOT EXISTS.

Запуск (Render Shell или локально):
    cd pospro_new_server
    python -u -m migrations.apply_products_block_customization
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'add_products_block_customization.sql')


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    # Один statement из DO $$ … $$ — выполняется целиком, не split.
    print('Applying migration: add_products_block_customization', flush=True)
    db.session.execute(text(sql))
    db.session.commit()

    # Проверка
    for col in ('background_color', 'show_products_categories_filter'):
        row = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'homepage_blocks' AND column_name = :c"
        ), {'c': col}).first()
        print(f'  {col}: {"OK" if row else "MISSING"}', flush=True)
    print('Done', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
