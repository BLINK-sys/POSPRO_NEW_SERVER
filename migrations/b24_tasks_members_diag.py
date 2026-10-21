"""
Readonly diag: разные API для получения accomplices/auditors задачи.
Пробуем на задаче, у которой гарантированно есть соисполнители.

Берём b24_id из нашей таблицы b24_mirror по pospro_id task#2 (там я
руками видел observers в UI) ИЛИ по аргументу --b24-id N.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from migrations.bitrix24._b24 import call


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--b24-id', type=str, default=None)
    p.add_argument('--pospro-id', type=int, default=None)
    args = p.parse_args()

    with app.app_context():
        b24_id = args.b24_id
        if not b24_id:
            # fallback — последняя задача с наибольшим id в mirror
            pid = args.pospro_id
            if pid is None:
                row = db.session.execute(text("""
                    SELECT b24_id FROM b24_mirror
                     WHERE entity_type='task'
                     ORDER BY CAST(b24_id AS INTEGER) DESC
                     LIMIT 1
                """)).fetchone()
                b24_id = row.b24_id if row else None
            else:
                row = db.session.execute(text("""
                    SELECT b24_id FROM b24_mirror
                     WHERE entity_type='task' AND pospro_id=:pid
                """), {'pid': pid}).fetchone()
                b24_id = row.b24_id if row else None
            if not b24_id:
                print('не нашёл b24_id', flush=True)
                return 1

        print(f'=== b24_id={b24_id} ===', flush=True)

        print('\n--- 1) tasks.task.get(taskId, [select]) UPPERCASE ---', flush=True)
        try:
            r = call('tasks.task.get', {
                'taskId': b24_id,
                'select[]': ['ID', 'TITLE', 'RESPONSIBLE_ID',
                             'ACCOMPLICES', 'AUDITORS'],
            })
            print(json.dumps(r.get('result'), ensure_ascii=False, indent=2)[:2500],
                  flush=True)
        except Exception as e:
            print(f'FAIL: {e}', flush=True)

        print('\n--- 2) tasks.task.get(taskId) без select — всё по умолчанию ---',
              flush=True)
        try:
            r = call('tasks.task.get', {'taskId': b24_id})
            full = r.get('result') or {}
            if isinstance(full, dict) and 'task' in full:
                task = full['task']
                # ключи, которые нам интересны
                for k in sorted(task.keys()):
                    if 'omplice' in k.lower() or 'uditor' in k.lower():
                        print(f'  {k}: {task[k]!r}', flush=True)
                print(f'  (всего ключей: {len(task)})', flush=True)
                print(f'  все ключи: {sorted(task.keys())}', flush=True)
            else:
                print(json.dumps(full, ensure_ascii=False, indent=2)[:1500],
                      flush=True)
        except Exception as e:
            print(f'FAIL: {e}', flush=True)

        print('\n--- 3) task.item.getdata(ID) — legacy API ---', flush=True)
        try:
            r = call('task.item.getdata', {'ID': b24_id})
            print(json.dumps(r.get('result'), ensure_ascii=False, indent=2)[:2500],
                  flush=True)
        except Exception as e:
            print(f'FAIL: {e}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
