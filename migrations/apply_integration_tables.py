"""
Разовая миграция: создать таблицы integration_settings / integration_run /
integration_command + стартовые записи settings для 'bio' и 'equip'.

Идемпотентна: `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING`.

Запуск (Render Shell или локально):
    cd pospro_new_server
    python -u -m migrations.apply_integration_tables
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'create_integration_tables.sql')


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    # Разбиваем по ';' и выполняем по одному statement — psycopg2 через
    # SQLAlchemy иначе может ругаться на multiple statements в одном execute.
    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

    print(f'Statements to execute: {len(statements)}', flush=True)
    for i, stmt in enumerate(statements, 1):
        first_line = stmt.splitlines()[0][:80]
        print(f'  [{i:>2}/{len(statements)}] {first_line}...', flush=True)
        db.session.execute(text(stmt))

    db.session.commit()

    # Проверим что таблицы созданы
    for tbl in ('integration_settings', 'integration_run', 'integration_command'):
        count = db.session.execute(text(f'SELECT COUNT(*) FROM {tbl}')).scalar()
        print(f'  {tbl}: {count} rows', flush=True)

    print('OK', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
