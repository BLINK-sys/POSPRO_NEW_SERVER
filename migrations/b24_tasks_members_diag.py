"""
Readonly diag: что реально возвращает B24 в accomplices/auditors для
5 последних задач. Нужно чтобы понять почему migrate_tasks не создал
ни одного TaskMember.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from migrations.bitrix24._b24 import call


SELECT = [
    'id', 'title', 'responsibleId', 'createdBy',
    'accomplices', 'auditors',
]


def main() -> int:
    with app.app_context():
        print('=== tasks.task.list — последние 5 с SELECT как в migrate ===',
              flush=True)
        r = call('tasks.task.list', {
            'select[]': SELECT,
            'order[ID]': 'DESC',
            'start': 0,
        })
        tasks = (r.get('result') or {}).get('tasks') or []
        for t in tasks[:5]:
            print(json.dumps(t, ensure_ascii=False, indent=2), flush=True)
            print('---', flush=True)

        # Для первой задачи — отдельно tasks.task.get, он обычно отдаёт
        # больше полей, в т.ч. accomplices/auditors гарантированно.
        if tasks:
            tid = tasks[0].get('id') or tasks[0].get('ID')
            print(f'\n=== tasks.task.get(id={tid}) полный ===', flush=True)
            r = call('tasks.task.get', {
                'taskId': tid,
                'select[]': SELECT,
            })
            print(json.dumps(r.get('result'), ensure_ascii=False, indent=2),
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
