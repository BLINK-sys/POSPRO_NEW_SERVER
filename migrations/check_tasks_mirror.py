"""
Readonly: сколько задач у нас и сколько замиррорено из B24.
Нужно чтобы понять, полностью ли мы импортировали задачи из Битрикса.

Также тянет текущий count задач из B24 через task.item.list (чтобы
сверить итоговое число — импорт мог быть сделан, но B24 с тех пор
нарастил новых задач).

Запуск:
    python -u -m migrations.check_tasks_mirror
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.task import Task
from migrations.bitrix24._b24 import call


def main() -> int:
    with app.app_context():
        total_tasks = db.session.query(db.func.count(Task.id)).scalar()
        mirrored = db.session.execute(text(
            "SELECT COUNT(*) FROM b24_mirror WHERE entity_type = 'task'"
        )).scalar()
        min_b24 = db.session.execute(text(
            "SELECT MIN(CAST(b24_id AS INTEGER)) FROM b24_mirror "
            "WHERE entity_type = 'task'"
        )).scalar()
        max_b24 = db.session.execute(text(
            "SELECT MAX(CAST(b24_id AS INTEGER)) FROM b24_mirror "
            "WHERE entity_type = 'task'"
        )).scalar()

        print('=== POSPRO ===', flush=True)
        print(f'  task всего:               {total_tasks}', flush=True)
        print(f'  b24_mirror task:          {mirrored}', flush=True)
        print(f'  b24_mirror range:         [{min_b24}..{max_b24}]', flush=True)
        print('', flush=True)

        # B24: берём total — одна страница с ORDER и NAV.start=0.
        print('=== B24 (tasks.task.list) ===', flush=True)
        try:
            r = call('tasks.task.list', {
                'select[]': ['ID'],
                'order[ID]': 'desc',
                'start': 0,
            })
            tasks_page = (r.get('result') or {}).get('tasks') or []
            b24_total = r.get('total') if 'total' in r else None
            print(f'  total (поле total ответа):  {b24_total}', flush=True)
            if tasks_page:
                last_b24_id = tasks_page[0].get('id') or tasks_page[0].get('ID')
                print(f'  последний task в B24:       id={last_b24_id}', flush=True)
            # Разница между max в нашей БД и max в B24.
            if last_b24_id and max_b24:
                try:
                    diff = int(last_b24_id) - int(max_b24)
                    print(f'  ΔID (B24.max − local.max):  {diff}', flush=True)
                except (ValueError, TypeError):
                    pass
        except Exception as e:
            print(f'  ошибка B24: {e}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
