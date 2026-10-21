"""
Backfill TaskMember для задач, импортированных из B24: migrate_tasks.py
использовал tasks.task.list который НЕ отдаёт accomplices/auditors.
По факту на 3664 задачах — 0 members (кроме руками добавленных).

Этот скрипт идёт по всем задачам с b24_mirror и для каждой:
  1. Берёт data через task.item.getdata(ID=b24_id) — отдаёт ACCOMPLICES/AUDITORS
  2. ACCOMPLICES → TaskMember role='co-worker'
     AUDITORS    → TaskMember role='observer'
  3. Пропускает если на задаче уже есть TaskMember (не затирает ручные)

Идемпотентно: при повторном запуске не создаёт дубли (проверка
(task_id, user_id) INSERT ON CONFLICT DO NOTHING через существование).

Dry-run по умолчанию.

Запуск:
    python -u -m migrations.backfill_task_members
    python -u -m migrations.backfill_task_members --apply
    python -u -m migrations.backfill_task_members --limit 50 --apply
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.task import Task, TaskMember
from models.systemuser import SystemUser

from migrations.bitrix24._b24 import call
from migrations.bitrix24._utils import load_mapping, user_pospro_id


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--limit', type=int, default=0,
                   help='Обработать только первые N задач (для теста)')
    p.add_argument('--skip', type=int, default=0,
                   help='Пропустить первые N задач')
    p.add_argument('--sleep', type=float, default=0.2,
                   help='Пауза между запросами в сек (защита от rate-limit B24)')
    return p.parse_args()


def _get_members_from_b24(b24_id: str) -> tuple[list[str], list[str]] | None:
    """Возвращает (accomplices_b24_ids, auditors_b24_ids) или None на ошибку."""
    try:
        r = call('task.item.getdata', {'ID': b24_id})
    except Exception as e:
        print(f'    B24 task.item.getdata({b24_id}) FAIL: {e}', flush=True)
        return None
    data = r.get('result') or {}
    acc = data.get('ACCOMPLICES') or []
    aud = data.get('AUDITORS') or []
    if isinstance(acc, str):
        acc = [acc]
    if isinstance(aud, str):
        aud = [aud]
    return (list(map(str, acc)), list(map(str, aud)))


def main() -> int:
    args = _parse_args()
    with app.app_context():
        mapping = load_mapping()
        owner = SystemUser.query.filter_by(is_owner=True).first()
        owner_id = owner.id if owner else 1

        # Все задачи с b24_mirror, у которых пока нет TaskMember.
        # (Если у юзера уже есть руками добавленные — считаем что он сам
        # разобрался; пропускаем.)
        rows = db.session.execute(text("""
            SELECT bm.b24_id, bm.pospro_id AS task_id
              FROM b24_mirror bm
              LEFT JOIN task_member tm ON tm.task_id = bm.pospro_id
             WHERE bm.entity_type = 'task'
               AND tm.id IS NULL
             ORDER BY CAST(bm.b24_id AS INTEGER)
        """)).fetchall()
        total_candidates = len(rows)
        if args.skip:
            rows = rows[args.skip:]
        if args.limit:
            rows = rows[:args.limit]

        print(f'=== backfill_task_members  mode={"APPLY" if args.apply else "DRY-RUN"}',
              flush=True)
        print(f'  задач-кандидатов (нет members): {total_candidates}', flush=True)
        print(f'  будем обрабатывать:             {len(rows)}', flush=True)
        print('', flush=True)

        n_proc = 0
        n_with_members = 0
        n_added = 0
        n_skipped = 0

        for i, row in enumerate(rows):
            b24_id = row.b24_id
            task_id = row.task_id

            res = _get_members_from_b24(b24_id)
            if res is None:
                n_skipped += 1
                time.sleep(args.sleep)
                continue
            acc, aud = res

            if not acc and not aud:
                n_proc += 1
                time.sleep(args.sleep)
                continue

            task = Task.query.get(task_id)
            if not task:
                n_skipped += 1
                time.sleep(args.sleep)
                continue
            responsible = task.responsible_id

            # Соисполнители (co-worker) + наблюдатели (observer).
            # Исключаем responsible и дубли (B24 допускает одного юзера
            # и в accomplices и в auditors — у нас TaskMember unique на
            # (task_id, user_id) не стоит, но логически нет смысла).
            co_worker_ids = []
            for aid in acc:
                pid = user_pospro_id(mapping, aid, 0)
                if pid and pid != responsible and pid not in co_worker_ids:
                    co_worker_ids.append(pid)
            observer_ids = []
            for aid in aud:
                pid = user_pospro_id(mapping, aid, 0)
                if (pid and pid != responsible
                        and pid not in observer_ids
                        and pid not in co_worker_ids):
                    observer_ids.append(pid)

            added_here = 0
            for uid in co_worker_ids:
                existing = TaskMember.query.filter_by(
                    task_id=task_id, user_id=uid,
                ).first()
                if existing:
                    continue
                added_here += 1
                if args.apply:
                    db.session.add(TaskMember(
                        task_id=task_id, user_id=uid, role='co-worker',
                    ))
            for uid in observer_ids:
                existing = TaskMember.query.filter_by(
                    task_id=task_id, user_id=uid,
                ).first()
                if existing:
                    continue
                added_here += 1
                if args.apply:
                    db.session.add(TaskMember(
                        task_id=task_id, user_id=uid, role='observer',
                    ))

            n_proc += 1
            if added_here:
                n_with_members += 1
                n_added += added_here

            if args.apply and n_proc % 50 == 0:
                db.session.commit()

            if n_proc % 100 == 0:
                print(f'    …{n_proc}/{len(rows)} '
                      f'(with_members={n_with_members}, added={n_added})',
                      flush=True)

            time.sleep(args.sleep)

        if args.apply:
            db.session.commit()

        print('', flush=True)
        print(f'=== TOTALS ===', flush=True)
        print(f'  обработано задач:         {n_proc}', flush=True)
        print(f'  задач с добавленными:     {n_with_members}', flush=True)
        print(f'  TaskMember добавлено:     {n_added}', flush=True)
        print(f'  пропущено (ошибки B24):   {n_skipped}', flush=True)
        if not args.apply:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
