"""
Диагностика: сравнивает что есть в B24 для tasks.task.list и что лежит
в нашей таблице task (из b24_mirror entity_type='task'). Нужен чтобы
понять почему при импорте что-то не долетело.

Печатает:
  - в B24: total, max/min ID, диапазон createdDate самых свежих 10 задач
  - у нас: count, max/min b24_id, диапазон created_at по импортированным,
    распределение по годам.

Запуск:
    python -u -m migrations.b24_tasks_diag
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from migrations.bitrix24._b24 import call


def _b24_sample(order_dir: str, label: str) -> None:
    """Берёт 10 задач из B24 с нужной сортировкой — чтобы увидеть
    самые свежие / самые старые."""
    try:
        out = call('tasks.task.list', {
            'select[]': ['id', 'title', 'createdDate'],
            'order[ID]': order_dir,
            'start': 0,
        })
    except Exception as e:
        print(f'  B24 {label} sample failed: {e}', flush=True)
        return
    result = out.get('result') or {}
    tasks = result.get('tasks') if isinstance(result, dict) else []
    if not tasks:
        print(f'  B24 {label} sample: пусто', flush=True)
        return
    print(f'  B24 {label} ({order_dir}) — первые 10:', flush=True)
    for t in tasks[:10]:
        print(f'     id={t.get("id"):>7}  created={t.get("createdDate")}  '
              f'{(t.get("title") or "")[:50]!r}',
              flush=True)
    # Служебная инфа — total / next с первой страницы
    print(f'  B24 pagination hint: total={out.get("total")}  next={out.get("next")}',
          flush=True)


def main() -> int:
    with app.app_context():
        print('=== B24 ===', flush=True)
        _b24_sample('DESC', 'самые свежие (DESC)')
        print('', flush=True)
        _b24_sample('ASC', 'самые старые (ASC)')
        print('', flush=True)

        print('=== PosPro (из b24_mirror entity_type=task) ===', flush=True)
        row = db.session.execute(text("""
            SELECT COUNT(*)                       AS cnt,
                   MIN(CAST(b24_id AS INTEGER))   AS min_b24_id,
                   MAX(CAST(b24_id AS INTEGER))   AS max_b24_id
            FROM b24_mirror
            WHERE entity_type = 'task'
        """)).fetchone()
        print(f'  mirror.count={row.cnt}  min_b24={row.min_b24_id}  '
              f'max_b24={row.max_b24_id}', flush=True)

        # Задачи с датами из task по id из mirror
        print('', flush=True)
        print('  Распределение по годам task.created_at:', flush=True)
        year_rows = db.session.execute(text("""
            SELECT EXTRACT(YEAR FROM t.created_at)::int AS yr, COUNT(*) AS c
            FROM task t
            WHERE t.id IN (
                SELECT pospro_id FROM b24_mirror WHERE entity_type = 'task'
            )
            GROUP BY yr
            ORDER BY yr
        """)).fetchall()
        for r in year_rows:
            print(f'    {r.yr}: {r.c}', flush=True)

        # Max created_at — последняя импортированная
        maxrow = db.session.execute(text("""
            SELECT MAX(t.created_at) AS mx
            FROM task t
            WHERE t.id IN (
                SELECT pospro_id FROM b24_mirror WHERE entity_type = 'task'
            )
        """)).fetchone()
        print(f'  max(created_at) среди импортированных: {maxrow.mx}',
              flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
