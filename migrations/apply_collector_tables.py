"""
Разовая миграция для таблиц collector_* (см. models/collector.py).
Идёмпотентна: CREATE TABLE IF NOT EXISTS + сингл-row insert через ON CONFLICT.

Запуск (Render Shell или локально):
    cd pospro_new_server
    python -u -m migrations.apply_collector_tables
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'create_collector_tables.sql')


def _strip_line_comments(sql: str) -> str:
    """Убирает `-- ...` до конца строки. Так '';' внутри комментария больше
    не путает наивный `split(';')` — было же: комментарий `по ';' построчно`
    рубился ровно на этом `';`, кусок после становился псевдо-statement'ом,
    PG падал с syntax error."""
    return re.sub(r'--[^\n]*', '', sql)


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = _strip_line_comments(f.read())

    statements = [s.strip() for s in sql.split(';') if s.strip()]
    print(f'Statements to execute: {len(statements)}', flush=True)
    for i, stmt in enumerate(statements, 1):
        first_line = stmt.splitlines()[0][:80]
        print(f'  [{i:>2}/{len(statements)}] {first_line}...', flush=True)
        db.session.execute(text(stmt))
    db.session.commit()

    for tbl in ('collector_task', 'collector_file', 'collector_command', 'collector_worker'):
        count = db.session.execute(text(f'SELECT COUNT(*) FROM {tbl}')).scalar()
        print(f'  {tbl}: {count} rows', flush=True)

    print('OK', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
