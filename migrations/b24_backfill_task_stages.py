"""
Бэкфилл Task.project_stage_id для задач, уже привязанных к проектам
через `b24_import_projects.py`.

Предыдущий импорт просто проставлял `project_id`, не трогая стадию
(у Task нет b24_data с STAGE_ID). Отсюда в канбане все задачи падают
в колонку «Без колонки». Этот скрипт:
  1) проходит по всем Project'ам, у которых есть b24_mirror(entity_type='project');
  2) дёргает tasks.task.list(filter={GROUP_ID: gid}, select=['ID','STAGE_ID']);
  3) для каждой задачи:
       Task.id   ← b24_mirror(entity_type='task', b24_id=t.ID).pospro_id
       stage.id  ← b24_mirror(entity_type='project_stage', b24_id=t.STAGE_ID).pospro_id
     и ставит `task.project_stage_id = stage.id`, только там, где поле
     пустое или не соответствует. `task.status` НЕ трогаем — могли
     вручную поменять уже после импорта.

Идемпотентен. Повторный запуск — no-op.

Запуск:
    python -u -m migrations.b24_backfill_task_stages           # dry-run
    python -u -m migrations.b24_backfill_task_stages --apply   # пишет
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from app import app
from extensions import db


HTTP_TIMEOUT = (15, 60)


def _main_webhook() -> str:
    url = os.environ.get('B24_WEBHOOK', '').strip()
    if not url:
        raise RuntimeError('B24_WEBHOOK env var is not set')
    return url


def _call(base_url: str, method: str, params: dict | None = None) -> dict:
    url = f'{base_url.rstrip("/")}/{method}.json'
    r = requests.post(url, json=params or {}, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f'{method} HTTP {r.status_code}: {r.text[:400]}')
    return r.json()


def _fetch_group_tasks(group_id: int) -> list[dict]:
    """[{id, stageId}, ...] — все задачи группы, из tasks.task.list."""
    out: list[dict] = []
    start = 0
    wm = _main_webhook()
    while True:
        resp = _call(wm, 'tasks.task.list', {
            'filter': {'GROUP_ID': group_id},
            'select': ['ID', 'STAGE_ID'],
            'start': start,
        })
        result = resp.get('result') or {}
        tasks = result.get('tasks') if isinstance(result, dict) else []
        if not tasks:
            break
        for t in tasks:
            tid = t.get('id') or t.get('ID')
            sid = t.get('stageId') or t.get('STAGE_ID')
            if tid is None:
                continue
            out.append({'id': str(tid), 'stage_id': str(sid) if sid not in (None, '', '0') else None})
        nxt = resp.get('next')
        if nxt is None:
            break
        start = int(nxt)
        if start > 200_000:
            break
    return out


def _load_project_mirrors() -> list[tuple[int, int]]:
    """[(b24_group_id, project_pospro_id), ...]"""
    rows = db.session.execute(
        db.text("""
            SELECT b24_id::int AS gid, pospro_id
              FROM b24_mirror
             WHERE entity_type = 'project'
             ORDER BY gid
        """)
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _load_task_map() -> dict[str, int]:
    """b24_task_id -> task.id (все наши зеркала задач)."""
    rows = db.session.execute(
        db.text("""
            SELECT b24_id, pospro_id
              FROM b24_mirror
             WHERE entity_type = 'task'
        """)
    ).fetchall()
    return {str(b24): int(pid) for (b24, pid) in rows}


def _load_stage_map() -> dict[str, int]:
    """b24_stage_id -> project_stage.id"""
    rows = db.session.execute(
        db.text("""
            SELECT b24_id, pospro_id
              FROM b24_mirror
             WHERE entity_type = 'project_stage'
        """)
    ).fetchall()
    return {str(b24): int(pid) for (b24, pid) in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='Пишет в БД. По умолчанию — dry-run.')
    args = parser.parse_args()

    print(f'Mode: {"APPLY" if args.apply else "DRY-RUN"}', flush=True)

    projects = _load_project_mirrors()
    if not projects:
        print('No projects in b24_mirror. Run b24_import_projects --apply first.', flush=True)
        return 0
    print(f'Projects with b24_mirror: {len(projects)}', flush=True)

    task_map = _load_task_map()
    stage_map = _load_stage_map()
    print(f'b24_mirror: tasks={len(task_map)}, stages={len(stage_map)}', flush=True)

    totals = Counter()
    for gid, project_id in projects:
        try:
            b24_tasks = _fetch_group_tasks(gid)
        except Exception as e:
            print(f'  #{gid} FAILED to fetch tasks: {e}', flush=True)
            totals['failed_groups'] += 1
            continue

        # Распределение по стадиям B24 (для отчёта)
        per_stage = Counter()

        # Собираем планируемые апдейты по стадиям: {stage_pospro_id: [task_pospro_id, ...]}
        plan: dict[int, list[int]] = defaultdict(list)
        missing_task = 0
        missing_stage = 0
        no_stage_in_b24 = 0

        for t in b24_tasks:
            b24_tid = t['id']
            b24_sid = t['stage_id']
            per_stage[b24_sid or '—'] += 1

            task_pid = task_map.get(b24_tid)
            if task_pid is None:
                # Задача существует в B24, но мы её не мигрировали. Это ожидаемо для
                # задач, которые у нас отфильтрованы миграцией (архив, удалённые и т.п.).
                missing_task += 1
                continue

            if not b24_sid:
                no_stage_in_b24 += 1
                continue

            stage_pid = stage_map.get(b24_sid)
            if stage_pid is None:
                # Стадия в B24 есть, но у нас её нет в mirror — мог быть
                # другой тип (личные/канбан пользователя). Пропускаем.
                missing_stage += 1
                continue

            plan[stage_pid].append(task_pid)

        # Отчёт на группу
        print(
            f'\n#{gid} → Project #{project_id}: '
            f'{len(b24_tasks)} b24 tasks, '
            f'need_update_groups={len(plan)}, '
            f'tasks_to_touch={sum(len(v) for v in plan.values())}, '
            f'skip_missing_task={missing_task}, '
            f'skip_missing_stage={missing_stage}, '
            f'skip_no_stage_in_b24={no_stage_in_b24}',
            flush=True,
        )

        totals['b24_tasks'] += len(b24_tasks)
        totals['skip_missing_task'] += missing_task
        totals['skip_missing_stage'] += missing_stage
        totals['skip_no_stage_in_b24'] += no_stage_in_b24
        totals['touch_candidates'] += sum(len(v) for v in plan.values())

        if not args.apply:
            # В dry-run: посчитать сколько РЕАЛЬНО обновится (уже проставленных не трогаем)
            if plan:
                would_update = 0
                for stage_pid, tids in plan.items():
                    rc = db.session.execute(
                        db.text("""
                            SELECT COUNT(*) FROM task
                             WHERE id = ANY(:ids)
                               AND project_id = :pid
                               AND (project_stage_id IS NULL OR project_stage_id <> :sid)
                        """),
                        {'ids': tids, 'pid': project_id, 'sid': stage_pid},
                    ).scalar()
                    would_update += rc or 0
                print(f'  would update: {would_update}', flush=True)
                totals['would_update'] += would_update
            continue

        # APPLY
        updated = 0
        for stage_pid, tids in plan.items():
            res = db.session.execute(
                db.text("""
                    UPDATE task
                       SET project_stage_id = :sid
                     WHERE id = ANY(:ids)
                       AND project_id = :pid
                       AND (project_stage_id IS NULL OR project_stage_id <> :sid)
                """),
                {'ids': tids, 'pid': project_id, 'sid': stage_pid},
            )
            updated += res.rowcount or 0
        db.session.commit()
        print(f'  UPDATED: {updated}', flush=True)
        totals['updated'] += updated

    print('\n=== SUMMARY ===', flush=True)
    for k, v in sorted(totals.items()):
        print(f'  {k}: {v}', flush=True)
    print(f'\n{"APPLIED" if args.apply else "DRY-RUN complete. Run with --apply to write."}', flush=True)
    return 0


if __name__ == '__main__':
    with app.app_context():
        sys.exit(main())
