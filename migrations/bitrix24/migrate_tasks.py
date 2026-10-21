"""
Миграция задач Б24 → `Task`.

Поля:
  - title       = TITLE
  - description = DESCRIPTION
  - priority    0=low, 1=normal, 2=high
  - status      1 NEW / 2 PENDING → pending
                3 IN_PROGRESS     → in_progress
                4 SUPPOSEDLY_COMPLETED → waiting_check
                5 COMPLETED       → done
                6 DEFERRED        → paused
                7 DECLINED        → done   (отклонённая закрыта)
  - responsible = RESPONSIBLE_ID → task.responsible_id (через user_map)
  - creator     = CREATED_BY     → task.creator_id
  - deal        = UF_CRM_TASK: ищем 'D_<n>' → b24_mirror('deal', n) → task.deal_id
  - due_at      = DEADLINE
  - started_at  = DATE_START
  - completed_at= CLOSED_DATE
  - members (из task.item.getdata batch — tasks.task.list их не отдаёт
    стабильно):
      ACCOMPLICES[] → TaskMember role='co-worker'
      AUDITORS[]    → TaskMember role='observer'

Идемпотентно через b24_mirror('task').

CLI:
  python -u -m migrations.bitrix24.migrate_tasks [--limit N] [--dry-run]
"""

import os
import sys
import argparse
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db
from sqlalchemy import text as sql_text

from models.systemuser import SystemUser
from models.task import Task, TaskMember

from migrations.bitrix24._b24 import call, _webhook_base
from migrations.bitrix24._utils import (
    load_mapping, user_pospro_id,
    mirror_get, mirror_set,
)


# Сколько задач за один прогон миграции обогащаем в одном batch-запросе
# к B24. B24 жёстко лимитирует 50 команд в batch.json.
_ENRICH_BATCH = 50


def _b24_batch(cmds: dict) -> dict:
    """
    POST /batch.json с набором команд.
    cmds = {name: (method, params_dict)}.
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


def _enrich_members(tasks: list[dict]) -> None:
    """
    В tasks.task.list поля `accomplices`/`auditors` часто отсутствуют или
    приходят неполные (B24 глюк). Для надёжности подтягиваем их отдельно
    через `task.item.getdata` батчем по 50 и дозаписываем в сами объекты.

    Мутирует `tasks` на месте: добавляет/перезаписывает ключи
    'accomplices' и 'auditors' значениями из getdata (если тот вернул
    что-то непустое).
    """
    if not tasks:
        return
    cmds = {}
    for t in tasks:
        tid = str(t.get('id') or t.get('ID') or '')
        if tid:
            cmds[f'id{tid}'] = ('task.item.getdata', {'ID': tid})
    if not cmds:
        return
    try:
        br = _b24_batch(cmds)
    except Exception as e:
        print(f'  WARN: enrich_members batch FAIL: {e}', flush=True)
        return
    for t in tasks:
        tid = str(t.get('id') or t.get('ID') or '')
        if not tid:
            continue
        data = br.get(f'id{tid}') or {}
        acc = data.get('ACCOMPLICES')
        aud = data.get('AUDITORS')
        if acc:
            t['accomplices'] = acc
        if aud:
            t['auditors'] = aud


def iter_tasks_by_id(select_fields: list[str]):
    """
    Пагинация tasks.task.list через `filter[>ID]=<last_id>` вместо
    стандартного start-cursor'а. Нужна потому что start-пагинация в
    tasks.task.list глохнет где-то после ~2500 задач (iter_list срабатывает
    защитой nxt_i<=start — возвращает кривой cursor).

    ORDER BY ID ASC — задачи идут от самых старых к свежим.
    """
    last_id = 0
    while True:
        out = call('tasks.task.list', {
            'select[]': select_fields,
            'order[ID]': 'ASC',
            'filter[>ID]': last_id,
            'start': 0,  # «отключаем» встроенную пагинацию: каждый запрос
                         # с нуля, фильтр по ID двигает курсор.
        })
        result = out.get('result') or {}
        tasks = result.get('tasks') if isinstance(result, dict) else []
        if not tasks:
            return
        for t in tasks:
            yield t
        try:
            last_id = max(int(t.get('id') or 0) for t in tasks)
        except (TypeError, ValueError):
            return
        if last_id <= 0:
            return


# tasks.task.list использует другие имена полей и nested selection:
# все поля — через select[] = ['id', 'title', ...] + list в query
FIELDS = [
    'id', 'title', 'description', 'priority', 'status',
    'responsibleId', 'createdBy',
    'deadline', 'startDatePlan', 'closedDate', 'createdDate',
    'ufCrmTask',  # связи с CRM-сущностями
    'accomplices', 'auditors',
]


B24_STATUS_MAP = {
    '1': 'pending',          # NEW
    '2': 'pending',          # PENDING (ожидает выполнения)
    '3': 'in_progress',      # IN_PROGRESS
    '4': 'waiting_check',    # SUPPOSEDLY_COMPLETED (ждёт приёма)
    '5': 'done',             # COMPLETED
    '6': 'paused',           # DEFERRED
    '7': 'done',             # DECLINED (отклонена = закрыта)
}

B24_PRIORITY_MAP = {
    '0': 'low',
    '1': 'normal',
    '2': 'high',
}


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except Exception:
        return None


def _deal_id_from_ufcrm(ufcrm) -> str | None:
    """
    UF_CRM_TASK в Б24: массив строк вида ['D_123', 'C_456', 'CO_789'].
    D_ = deal, C_ = contact, CO_ = company. Берём первую D_.
    """
    if not ufcrm:
        return None
    if isinstance(ufcrm, str):
        ufcrm = [ufcrm]
    for s in ufcrm:
        m = re.match(r'^D_(\d+)$', str(s))
        if m:
            return m.group(1)
    return None


def migrate_one(
    t: dict,
    mapping: dict,
    owner_id: int,
    valid_user_ids: set[int],
    dry_run: bool,
) -> str:
    b24_id = str(t.get('id') or t.get('ID'))
    if not b24_id:
        return 'skip (no id)'
    existing_pid = mirror_get('task', b24_id)
    if existing_pid:
        return f'skip (already imported → #{existing_pid})'

    title = (t.get('title') or '').strip() or f'B24 task #{b24_id}'
    description = t.get('description') or None
    status_raw = str(t.get('status') or '2')
    status = B24_STATUS_MAP.get(status_raw, 'pending')
    prio_raw = str(t.get('priority') or '1')
    priority = B24_PRIORITY_MAP.get(prio_raw, 'normal')

    responsible = user_pospro_id(mapping, t.get('responsibleId'), owner_id)
    creator = user_pospro_id(mapping, t.get('createdBy'), owner_id)

    due_at = _parse_dt(t.get('deadline'))
    started_at = _parse_dt(t.get('startDatePlan'))
    completed_at = _parse_dt(t.get('closedDate'))
    created_at = _parse_dt(t.get('createdDate')) or datetime.utcnow()

    deal_b24 = _deal_id_from_ufcrm(t.get('ufCrmTask'))
    deal_pid = mirror_get('deal', deal_b24) if deal_b24 else None

    accomplices = t.get('accomplices') or []
    auditors = t.get('auditors') or []
    if isinstance(accomplices, str):
        accomplices = [accomplices]
    if isinstance(auditors, str):
        auditors = [auditors]

    # Фильтр `pid in valid_user_ids` защищает от FK-ошибки на уже
    # удалённого в system_users юзера (сам маппинг держит pospro_id,
    # но тот юзер мог быть удалён вручную позже).
    co_worker_ids = []
    for aid in accomplices:
        pid = user_pospro_id(mapping, aid, 0)
        if (pid and pid != responsible
                and pid in valid_user_ids
                and pid not in co_worker_ids):
            co_worker_ids.append(pid)
    observer_ids = []
    for aid in auditors:
        pid = user_pospro_id(mapping, aid, 0)
        if (pid and pid != responsible
                and pid in valid_user_ids
                and pid not in observer_ids
                and pid not in co_worker_ids):
            observer_ids.append(pid)

    if dry_run:
        return (f'[dry-run] would create: {title[:50]!r} status={status} '
                f'resp=#{responsible} creator=#{creator} deal_pid={deal_pid} '
                f'coworkers={len(co_worker_ids)} observers={len(observer_ids)}')

    task = Task(
        title=title[:255],
        description=description,
        priority=priority,
        status=status,
        responsible_id=responsible,
        creator_id=creator,
        deal_id=deal_pid,
        due_at=due_at,
        started_at=started_at,
        completed_at=completed_at,
        created_at=created_at,
    )
    db.session.add(task)
    db.session.flush()

    for uid in co_worker_ids:
        db.session.add(TaskMember(task_id=task.id, user_id=uid, role='co-worker'))
    for uid in observer_ids:
        db.session.add(TaskMember(task_id=task.id, user_id=uid, role='observer'))

    mirror_set('task', b24_id, task.id)
    return (f'created #{task.id} {title[:40]!r} '
            f'(status={status}, members={len(co_worker_ids) + len(observer_ids)})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print(f'=== migrate_tasks  limit={args.limit or "ALL"}  dry_run={args.dry_run} ===',
          flush=True)

    with app.app_context():
        mapping = load_mapping()
        owner = SystemUser.query.filter_by(is_owner=True).first()
        owner_id = owner.id
        # Чтобы при вставке TaskMember не словить FK на удалённого юзера.
        valid_user_ids = {
            r[0] for r in db.session.execute(
                sql_text("SELECT id FROM system_users")
            )
        }

        n_total = n_created = n_skipped = 0
        # Используем ID-пагинацию (iter_tasks_by_id) вместо стандартного
        # iter_list — у tasks.task.list start-cursor глючит после ~2500
        # записей, из-за чего прошлый импорт остановился на апреле 2024.
        # Копим чанками по _ENRICH_BATCH, обогащаем ACCOMPLICES/AUDITORS
        # одним batch-запросом к B24 (tasks.task.list их отдаёт нестабильно).
        buffer: list[dict] = []

        def _flush(chunk: list[dict]) -> bool:
            """Обработать накопленный чанк. Возвращает True если юзер
            попросил --limit и мы его исчерпали."""
            nonlocal n_total, n_created, n_skipped
            if not chunk:
                return False
            _enrich_members(chunk)
            for t in chunk:
                n_total += 1
                try:
                    result = migrate_one(
                        t, mapping, owner_id, valid_user_ids, args.dry_run,
                    )
                except Exception as e:
                    db.session.rollback()
                    result = f'ERROR: {e}'
                if result.startswith('skip'):
                    n_skipped += 1
                elif 'created' in result or 'would create' in result:
                    n_created += 1
                if n_total <= 30 or n_total % 200 == 0:
                    print(f'  [{n_total:5d}] b24#{t.get("id"):>7}  {result}',
                          flush=True)
                if args.limit and n_total >= args.limit:
                    return True
            if not args.dry_run:
                db.session.commit()
            return False

        stop = False
        for t in iter_tasks_by_id(FIELDS):
            buffer.append(t)
            if len(buffer) >= _ENRICH_BATCH:
                stop = _flush(buffer)
                buffer = []
                if stop:
                    break
        if not stop:
            _flush(buffer)

        if not args.dry_run:
            db.session.commit()

        print(f'\n=== TOTALS ===', flush=True)
        print(f'  processed: {n_total}', flush=True)
        print(f'  created:   {n_created}', flush=True)
        print(f'  skipped:   {n_skipped}', flush=True)


if __name__ == '__main__':
    main()
