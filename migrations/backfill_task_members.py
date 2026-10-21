"""
Backfill TaskMember для задач из B24.

v2: использует B24 batch (до 50 задач за один HTTP) → полная миграция
3600+ задач проходит за ~30-60 секунд вместо ~30 минут.

Также заботится о Postgres connection pool: закрывает сессию после
каждого batch'а, чтобы параллельный deploy мог поднять gunicorn.

Запуск:
    python -u -m migrations.backfill_task_members                 # dry-run
    python -u -m migrations.backfill_task_members --apply
    python -u -m migrations.backfill_task_members --batch 50 --apply
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.task import TaskMember
from models.systemuser import SystemUser
from migrations.bitrix24._b24 import _webhook_base
from migrations.bitrix24._utils import load_mapping, user_pospro_id


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--batch', type=int, default=50,
                   help='Задач за один B24 batch-запрос (макс 50)')
    p.add_argument('--limit', type=int, default=0,
                   help='Обработать только первые N задач (для теста)')
    return p.parse_args()


def _b24_batch(cmds: dict) -> dict:
    """
    POST /batch.json с набором команд. cmds = {name: (method, params)}.
    Возвращает {name: result} из `result.result`.
    """
    url = _webhook_base() + '/batch.json'
    flat = {'halt': 0}
    for name, (method, params) in cmds.items():
        qs = urllib.parse.urlencode(params or {}, doseq=True)
        flat[f'cmd[{name}]'] = f'{method}?{qs}' if qs else method
    data = urllib.parse.urlencode(flat, doseq=True).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode('utf-8')
    out = json.loads(body)
    return (out.get('result') or {}).get('result') or {}


def main() -> int:
    args = _parse_args()
    with app.app_context():
        mapping = load_mapping()
        owner = SystemUser.query.filter_by(is_owner=True).first()
        owner_id = owner.id if owner else 1

        rows = db.session.execute(text("""
            SELECT bm.b24_id, bm.pospro_id AS task_id,
                   t.responsible_id
              FROM b24_mirror bm
              JOIN task t ON t.id = bm.pospro_id
              LEFT JOIN task_member tm ON tm.task_id = bm.pospro_id
             WHERE bm.entity_type = 'task'
               AND tm.id IS NULL
             ORDER BY CAST(bm.b24_id AS INTEGER) DESC
        """)).fetchall()
        if args.limit:
            rows = rows[:args.limit]

        total = len(rows)
        print(f'=== backfill_task_members v2  '
              f'mode={"APPLY" if args.apply else "DRY-RUN"}', flush=True)
        print(f'  задач-кандидатов: {total}', flush=True)
        print(f'  batch size:       {args.batch}', flush=True)
        print('', flush=True)

        # Освобождаем сессию перед долгим B24 — иначе транзакция держит
        # Postgres connection всё время запроса (а он может быть долгим).
        db.session.remove()

        n_proc = 0
        n_with_members = 0
        n_added = 0
        n_batches = 0
        t0 = time.time()

        for i in range(0, len(rows), args.batch):
            chunk = rows[i:i + args.batch]
            cmds = {}
            for r in chunk:
                cmds[f'id{r.b24_id}'] = ('task.item.getdata', {'ID': r.b24_id})
            try:
                br = _b24_batch(cmds)
            except Exception as e:
                print(f'  B24 batch @{i} FAIL: {e}', flush=True)
                continue
            n_batches += 1

            # Собираем все инсерты для этого batch'а в одну транзакцию.
            inserts: list[tuple[int, int, str]] = []
            for r in chunk:
                b24_id = r.b24_id
                task_id = r.task_id
                responsible = r.responsible_id
                data = br.get(f'id{b24_id}') or {}
                acc = data.get('ACCOMPLICES') or []
                aud = data.get('AUDITORS') or []
                if isinstance(acc, str):
                    acc = [acc]
                if isinstance(aud, str):
                    aud = [aud]

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

                here = 0
                for uid in co_worker_ids:
                    inserts.append((task_id, uid, 'co-worker'))
                    here += 1
                for uid in observer_ids:
                    inserts.append((task_id, uid, 'observer'))
                    here += 1
                if here:
                    n_with_members += 1
                    n_added += here
                n_proc += 1

            if args.apply and inserts:
                # ON CONFLICT DO NOTHING защищает если вдруг кто-то параллельно
                # что-то добавил (хотя у task_member нет уникального индекса —
                # на всякий случай сверим с существующими).
                existing = db.session.execute(text("""
                    SELECT task_id, user_id FROM task_member
                     WHERE task_id = ANY(:tids)
                """), {'tids': list({t for t, _, _ in inserts})}).fetchall()
                have = {(e.task_id, e.user_id) for e in existing}
                new = [(tid, uid, role) for tid, uid, role in inserts
                       if (tid, uid) not in have]
                if new:
                    db.session.execute(text("""
                        INSERT INTO task_member (task_id, user_id, role,
                                                 created_at, updated_at)
                        VALUES (:tid, :uid, :role, NOW(), NOW())
                    """), [{'tid': t, 'uid': u, 'role': r} for t, u, r in new])
                db.session.commit()
                # Чтобы не держать соединение всю миграцию:
                db.session.remove()

            if n_batches % 5 == 0:
                dt = time.time() - t0
                print(f'    …{n_proc}/{total}  with_members={n_with_members} '
                      f'added={n_added}  batches={n_batches} ({dt:.1f}s)',
                      flush=True)

        dt = time.time() - t0
        print('', flush=True)
        print(f'=== TOTALS ({dt:.1f}s) ===', flush=True)
        print(f'  обработано задач:         {n_proc}', flush=True)
        print(f'  задач с добавленными:     {n_with_members}', flush=True)
        print(f'  TaskMember добавлено:     {n_added}', flush=True)
        print(f'  B24 batch-запросов:       {n_batches}', flush=True)
        if not args.apply:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
