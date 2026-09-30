"""
Одноразовый cleanup «залипших» участников чатов сделок/задач.

Запуск через Render Job:
    python -u -m migrations.apply_cleanup_chat_members
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(
    os.path.dirname(__file__), 'cleanup_chat_members_orphans.sql',
)


def _split_statements(sql: str):
    for stmt in sql.split(';'):
        s = stmt.strip()
        if s:
            yield s


def apply():
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    # Считаем до и после — чтобы видеть эффект.
    before_deal = db.session.execute(text(
        "SELECT COUNT(*) FROM chat_member cm JOIN chat_room r ON r.id = cm.room_id "
        "WHERE r.kind = 'deal'"
    )).scalar()
    before_task = db.session.execute(text(
        "SELECT COUNT(*) FROM chat_member cm JOIN chat_room r ON r.id = cm.room_id "
        "WHERE r.kind = 'task'"
    )).scalar()
    print(f'  before: deal-chat members = {before_deal}, task-chat members = {before_task}', flush=True)

    print('Applying cleanup: chat_member orphans in deal/task rooms', flush=True)
    for stmt in _split_statements(sql):
        db.session.execute(text(stmt))
    db.session.commit()

    after_deal = db.session.execute(text(
        "SELECT COUNT(*) FROM chat_member cm JOIN chat_room r ON r.id = cm.room_id "
        "WHERE r.kind = 'deal'"
    )).scalar()
    after_task = db.session.execute(text(
        "SELECT COUNT(*) FROM chat_member cm JOIN chat_room r ON r.id = cm.room_id "
        "WHERE r.kind = 'task'"
    )).scalar()
    print(f'  after: deal-chat members = {after_deal}, task-chat members = {after_task}', flush=True)
    print(f'  removed: {before_deal - after_deal} from deal, {before_task - after_task} from task', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
