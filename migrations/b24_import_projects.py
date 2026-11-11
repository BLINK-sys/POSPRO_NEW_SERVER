"""
Импорт рабочих групп (проектов) из Bitrix24 в наш `Project`.

Из B24 тянем три вещи:
  - sonet_group.get           — список групп (B24_WEBHOOK_PROJECTS)
  - sonet_group.user.get      — участники группы (B24_WEBHOOK_PROJECTS)
  - task.stages.get           — стадии канбана задач группы (B24_WEBHOOK)
  - user.get                  — профили юзеров для резолва email (B24_WEBHOOK_PROJECTS)

Что создаём в нашей БД:
  - Project — по одной на каждую B24-группу (B24Mirror entity_type='project').
    Имя/описание/статус/owner маппим. Цвет — дефолтный brand-yellow
    (у рабочих групп B24 нет своего цвета).
  - ProjectStage — по одной на каждую стадию задач группы в B24
    (B24Mirror entity_type='project_stage'). maps_to_status эвристикой:
      SYSTEM_TYPE=NEW    → 'pending'
      SYSTEM_TYPE=FINISH → 'done'
      всё остальное      → 'in_progress'
    SORT переносим как sort_order, цвет — из B24 (нормализуем hex).
  - ProjectMemberSettings — для участников с ролями A (admin) и E (moderator)
    выставляем can_see_all_tasks=True. Обычных участников (K) не трогаем —
    дефолт False (видят только свои задачи). Резолвим юзеров по email
    через user.get → SystemUser.email.
  - Task.project_id — проставляем для уже импортированных задач, у которых
    b24_data содержит groupId этой группы.

Идемпотентность — через `B24Mirror`. Повторный запуск не плодит дубли,
обновляет имена/стадии/привязки задач.

Запуск:
    python -u -m migrations.b24_import_projects            # dry-run
    python -u -m migrations.b24_import_projects --apply    # пишет в БД
"""

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from app import app
from extensions import db
from models.systemuser import SystemUser
from models.project import Project, ProjectStage, ProjectMemberSettings
from models.task import Task
from models.b24_mirror import B24Mirror


HTTP_TIMEOUT = (15, 60)


def _call(base_url: str, method: str, params: dict | None = None) -> dict:
    url = f'{base_url.rstrip("/")}/{method}.json'
    r = requests.post(url, json=params or {}, timeout=HTTP_TIMEOUT)
    body = r.text
    if r.status_code != 200:
        raise RuntimeError(f'{method} HTTP {r.status_code}: {body[:400]}')
    return r.json()


def _projects_webhook() -> str:
    url = os.environ.get('B24_WEBHOOK_PROJECTS', '').strip()
    if not url:
        raise RuntimeError('B24_WEBHOOK_PROJECTS env var is not set')
    return url


def _main_webhook() -> str:
    url = os.environ.get('B24_WEBHOOK', '').strip()
    if not url:
        raise RuntimeError('B24_WEBHOOK env var is not set')
    return url


def _fetch_all_groups() -> list[dict]:
    """sonet_group.get с пагинацией. Возвращаем всё, фильтрацию делаем
    дальше по PROJECT=Y / CLOSED=N, чтобы оставить гибкость."""
    groups: list[dict] = []
    start = 0
    wp = _projects_webhook()
    while True:
        out = _call(wp, 'sonet_group.get', {
            'ORDER[ID]': 'ASC',
            'start': start,
        })
        batch = out.get('result') or []
        if isinstance(batch, dict):
            batch = list(batch.values())
        if not batch:
            break
        groups.extend(batch)
        nxt = out.get('next')
        if nxt is None:
            break
        start = int(nxt)
        if start > 100_000:
            break
    return groups


def _fetch_group_users(group_id: int) -> list[dict]:
    """sonet_group.user.get — [{USER_ID, ROLE}]. Роли:
       A=admin, E=moderator, K=user, B=banned."""
    out = _call(_projects_webhook(), 'sonet_group.user.get', {'ID': group_id})
    res = out.get('result') or []
    return res if isinstance(res, list) else []


def _fetch_group_task_ids(group_id: int) -> list[int]:
    """tasks.task.list?filter[GROUP_ID]=<gid> — все id задач группы.
       Пагинируем через start, select только id для скорости."""
    ids: list[int] = []
    start = 0
    wm = _main_webhook()
    while True:
        out = _call(wm, 'tasks.task.list', {
            'filter[GROUP_ID]': group_id,
            'select[]': ['id'],
            'start': start,
        })
        result = out.get('result') or {}
        tasks = result.get('tasks') if isinstance(result, dict) else []
        if not tasks:
            break
        for t in tasks:
            try:
                ids.append(int(t.get('id') or t.get('ID')))
            except (TypeError, ValueError):
                continue
        nxt = out.get('next')
        if nxt is None:
            break
        start = int(nxt)
        if start > 200_000:
            break
    return ids


def _fetch_group_stages(group_id: int) -> list[dict]:
    """task.stages.get через основной вебхук (у него scope task).
       isAdmin=Y — чтобы видеть все стадии, даже если юзер не админ группы."""
    out = _call(_main_webhook(), 'task.stages.get', {
        'entityId': group_id, 'isAdmin': 'Y',
    })
    res = out.get('result') or {}
    if isinstance(res, dict):
        return list(res.values())
    return res if isinstance(res, list) else []


def _fetch_user(b24_user_id: int) -> dict | None:
    out = _call(_projects_webhook(), 'user.get', {'ID': b24_user_id})
    res = out.get('result') or []
    if isinstance(res, list) and res:
        return res[0]
    return None


def _normalize_hex(color: str | None) -> str:
    """B24 возвращает цвета без '#' и иногда в верхнем/нижнем регистре.
       Приводим к '#RRGGBB'. Если пусто или битый — дефолт серый."""
    if not color:
        return '#94a3b8'
    c = str(color).strip().lstrip('#')
    if len(c) == 6:
        try:
            int(c, 16)
            return '#' + c.upper()
        except ValueError:
            pass
    return '#94a3b8'


def _maps_to_status(stage: dict) -> str:
    st = str(stage.get('SYSTEM_TYPE') or '').upper()
    if st == 'NEW':
        return 'pending'
    if st == 'FINISH':
        return 'done'
    return 'in_progress'


def _find_mirror(entity_type: str, b24_id: str) -> B24Mirror | None:
    return B24Mirror.query.filter_by(
        entity_type=entity_type, b24_id=str(b24_id),
    ).first()


def _upsert_mirror(entity_type: str, b24_id: str, pospro_id: int) -> None:
    m = _find_mirror(entity_type, b24_id)
    if m is None:
        db.session.add(B24Mirror(
            entity_type=entity_type, b24_id=str(b24_id), pospro_id=pospro_id,
            migration_tag='projects',
        ))


class UserResolver:
    """Кэш резолва B24 user_id → SystemUser (по email).
       Миссы помним, чтобы не дёргать user.get повторно."""

    def __init__(self):
        self._by_b24: dict[int, SystemUser | None] = {}

    def get(self, b24_user_id: int) -> SystemUser | None:
        if b24_user_id in self._by_b24:
            return self._by_b24[b24_user_id]
        try:
            profile = _fetch_user(b24_user_id)
        except Exception as e:
            print(f'    WARN user.get({b24_user_id}) failed: {e}', flush=True)
            self._by_b24[b24_user_id] = None
            return None
        email = (profile or {}).get('EMAIL')
        user = None
        if email:
            user = SystemUser.query.filter(
                db.func.lower(SystemUser.email) == email.lower()
            ).first()
        self._by_b24[b24_user_id] = user
        return user


def plan_for_group(
    group: dict, resolver: UserResolver,
) -> dict:
    """Собрать всё что надо знать про группу, не трогая БД. Возвращает
    словарь с действиями — на основе него уже и apply, и dry-run отчёт."""
    gid = int(group['ID'])
    existing_mirror = _find_mirror('project', str(gid))
    existing_project = (
        Project.query.get(existing_mirror.pospro_id)
        if existing_mirror else None
    )

    owner_b24 = int(group.get('OWNER_ID') or 0) or None
    owner = resolver.get(owner_b24) if owner_b24 else None

    # Стадии
    stages_src = _fetch_group_stages(gid)
    stages_plan = []
    for s in stages_src:
        sid = str(s.get('ID'))
        mirror = _find_mirror('project_stage', sid)
        stages_plan.append({
            'b24_id': sid,
            'name': (s.get('TITLE') or '').strip() or f'Стадия {sid}',
            'color': _normalize_hex(s.get('COLOR')),
            'sort_order': int(s.get('SORT') or 0),
            'maps_to_status': _maps_to_status(s),
            'system_type': (s.get('SYSTEM_TYPE') or '').upper() or None,
            'existing_id': mirror.pospro_id if mirror else None,
        })

    # Участники
    members = _fetch_group_users(gid)
    members_plan = []
    for m in members:
        uid_b24 = int(m.get('USER_ID') or 0) or None
        role = (m.get('ROLE') or '').upper()
        if not uid_b24:
            continue
        can_see_all = role in ('A', 'E')  # admin/moderator
        user = resolver.get(uid_b24)
        members_plan.append({
            'b24_user_id': uid_b24,
            'role': role,
            'user_id': user.id if user else None,
            'user_email': user.email if user else None,
            'can_see_all_tasks': can_see_all,
        })

    # Задачи — на нашей стороне в `task` groupId не сохранён. Тянем список
    # b24_id задач группы из B24 и ищем их в b24_mirror(entity_type='task').
    b24_task_ids = _fetch_group_task_ids(gid)
    task_ids = []
    if b24_task_ids:
        rows = db.session.execute(
            db.text("""
                SELECT pospro_id FROM b24_mirror
                 WHERE entity_type = 'task' AND b24_id = ANY(:ids)
            """),
            {'ids': [str(x) for x in b24_task_ids]},
        ).fetchall()
        task_ids = [r[0] for r in rows]
    task_count = len(task_ids)

    return {
        'b24_group_id': gid,
        'name': (group.get('NAME') or f'Group {gid}').strip(),
        'description': (group.get('DESCRIPTION') or '').strip() or None,
        'status': 'archived' if str(group.get('CLOSED', 'N')).upper() == 'Y' else 'active',
        'project_flag': str(group.get('PROJECT', 'N')).upper() == 'Y',
        'owner_b24_id': owner_b24,
        'owner_system_id': owner.id if owner else None,
        'owner_email': owner.email if owner else None,
        'existing_project_id': existing_project.id if existing_project else None,
        'existing_project_name': existing_project.name if existing_project else None,
        'stages': stages_plan,
        'members': members_plan,
        'task_ids': task_ids,
        'task_count': task_count,
        'b24_task_count': len(b24_task_ids),
    }


def print_dry_run(plan: dict) -> None:
    mark = 'UPDATE' if plan['existing_project_id'] else 'CREATE'
    print(f"\n#{plan['b24_group_id']}  [{mark}]  {plan['name']}", flush=True)
    print(f"  status={plan['status']}  project_flag={plan['project_flag']}", flush=True)
    owner_str = (
        f"owner=#{plan['owner_system_id']} ({plan['owner_email']})"
        if plan['owner_system_id'] else
        f"owner=? (B24 #{plan['owner_b24_id']}, not found in SystemUser)"
        if plan['owner_b24_id'] else 'owner=none'
    )
    print(f"  {owner_str}", flush=True)
    if plan['existing_project_id']:
        print(f"  → existing Project #{plan['existing_project_id']} ({plan['existing_project_name']!r})", flush=True)

    # Stages
    new_stages = sum(1 for s in plan['stages'] if not s['existing_id'])
    upd_stages = len(plan['stages']) - new_stages
    print(f"  stages: {len(plan['stages'])} total  (+{new_stages} new / {upd_stages} update)", flush=True)
    for s in plan['stages']:
        tag = 'NEW' if not s['existing_id'] else f"#{s['existing_id']}"
        sys_tag = f" [{s['system_type']}]" if s['system_type'] else ''
        print(
            f"    {tag:>6}  sort={s['sort_order']:<3} "
            f"→ {s['maps_to_status']:<13} {s['name']!r:<40}{sys_tag}",
            flush=True,
        )

    # Members
    all_members = len(plan['members'])
    resolved = sum(1 for m in plan['members'] if m['user_id'])
    see_all = sum(1 for m in plan['members'] if m['can_see_all_tasks'] and m['user_id'])
    print(f"  members: {all_members} total  ({resolved} resolved to SystemUser, {see_all} will get can_see_all_tasks)", flush=True)
    for m in plan['members']:
        status = (
            f"→ #{m['user_id']} {m['user_email']}" if m['user_id']
            else f"→ ??? (B24 user #{m['b24_user_id']} not in SystemUser)"
        )
        flag = ' *see_all*' if m['can_see_all_tasks'] else ''
        print(f"    [{m['role']}] B24#{m['b24_user_id']:<6} {status}{flag}", flush=True)

    # Tasks
    print(
        f"  tasks in B24 group: {plan['b24_task_count']}  "
        f"→ linkable (есть в b24_mirror): {plan['task_count']}",
        flush=True,
    )


def apply_plan(plan: dict) -> int:
    """Пишет изменения в БД. Возвращает id Project'а (нового или
    существующего) для возможного последующего привязывания задач."""
    gid = plan['b24_group_id']

    # Project
    if plan['existing_project_id']:
        project = Project.query.get(plan['existing_project_id'])
        if project is None:
            raise RuntimeError(
                f'B24Mirror указывает на Project #{plan["existing_project_id"]}, '
                f'но его нет в БД. Ручная чистка B24Mirror нужна.'
            )
        project.name = plan['name']
        project.description = plan['description']
        project.status = plan['status']
        project.owner_id = plan['owner_system_id']
    else:
        # Разрулить коллизию имени: project.name UNIQUE. Если имя уже
        # занято ручным проектом — добавляем суффикс ' (B24)'.
        name = plan['name']
        clash = Project.query.filter_by(name=name).first()
        if clash is not None:
            name = f'{name} (B24)'
            clash2 = Project.query.filter_by(name=name).first()
            if clash2 is not None:
                name = f'{plan["name"]} (B24 #{gid})'
        project = Project(
            name=name,
            color='#facc15',
            description=plan['description'],
            status=plan['status'],
            owner_id=plan['owner_system_id'],
            created_by=plan['owner_system_id'],
        )
        db.session.add(project)
        db.session.flush()
        _upsert_mirror('project', str(gid), project.id)

    # Stages
    seen_stage_ids = set()
    for s in plan['stages']:
        if s['existing_id']:
            stage = ProjectStage.query.get(s['existing_id'])
            if stage is None:
                # Mirror стух — пересоздадим.
                stage = ProjectStage(project_id=project.id, name=s['name'])
                db.session.add(stage)
                db.session.flush()
                _upsert_mirror('project_stage', s['b24_id'], stage.id)
            else:
                stage.project_id = project.id
                stage.name = s['name']
                stage.color = s['color']
                stage.sort_order = s['sort_order']
                stage.maps_to_status = s['maps_to_status']
        else:
            stage = ProjectStage(
                project_id=project.id,
                name=s['name'],
                color=s['color'],
                sort_order=s['sort_order'],
                maps_to_status=s['maps_to_status'],
            )
            db.session.add(stage)
            db.session.flush()
            _upsert_mirror('project_stage', s['b24_id'], stage.id)
        seen_stage_ids.add(stage.id)

    # Members (только can_see_all_tasks — остальные дефолтно False)
    for m in plan['members']:
        if not m['user_id'] or not m['can_see_all_tasks']:
            continue
        existing = ProjectMemberSettings.query.filter_by(
            project_id=project.id, user_id=m['user_id'],
        ).first()
        if existing:
            existing.can_see_all_tasks = True
        else:
            db.session.add(ProjectMemberSettings(
                project_id=project.id, user_id=m['user_id'],
                can_see_all_tasks=True,
            ))

    # Привязать задачи. Task.project_id ставим только там, где он NULL,
    # чтобы не перехватить задачу, вручную привязанную к другому проекту.
    if plan['task_ids']:
        linked = db.session.execute(
            db.text("""
                UPDATE task
                   SET project_id = :pid
                 WHERE id = ANY(:ids) AND project_id IS NULL
            """),
            {'pid': project.id, 'ids': plan['task_ids']},
        ).rowcount or 0
        if linked:
            print(f'  linked {linked} tasks → Project #{project.id}', flush=True)

    return project.id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='Пишет в БД. По умолчанию — dry-run.')
    parser.add_argument('--only-projects', action='store_true',
                        help='Пропускать группы с PROJECT=N '
                             '(оставить только помеченные как «проект»).')
    parser.add_argument('--skip-closed', action='store_true',
                        help='Пропускать CLOSED=Y группы.')
    parser.add_argument('--limit', type=int, default=0,
                        help='Ограничить число групп (0 = все).')
    args = parser.parse_args()

    print(f'Mode: {"APPLY" if args.apply else "DRY-RUN"}', flush=True)
    print('Fetching groups …', flush=True)
    groups = _fetch_all_groups()
    if args.only_projects:
        groups = [g for g in groups if str(g.get('PROJECT', 'N')).upper() == 'Y']
    if args.skip_closed:
        groups = [g for g in groups if str(g.get('CLOSED', 'N')).upper() != 'Y']
    if args.limit:
        groups = groups[:args.limit]
    print(f'Groups to process: {len(groups)}', flush=True)

    resolver = UserResolver()
    counters = Counter()
    for g in groups:
        try:
            plan = plan_for_group(g, resolver)
        except Exception as e:
            # rollback — иначе сессия остаётся в aborted state и
            # следующие SELECT'ы в plan_for_group тоже валятся.
            db.session.rollback()
            print(f'\n#{g.get("ID")}  FAILED to plan: {e}', flush=True)
            counters['failed'] += 1
            continue
        print_dry_run(plan)
        counters['total'] += 1
        counters['new' if not plan['existing_project_id'] else 'update'] += 1
        counters['new_stages'] += sum(1 for s in plan['stages'] if not s['existing_id'])
        counters['upd_stages'] += sum(1 for s in plan['stages'] if s['existing_id'])
        counters['tasks_linkable'] += plan['task_count']
        counters['tasks_in_b24'] += plan['b24_task_count']
        if args.apply:
            try:
                apply_plan(plan)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f'  APPLY FAILED: {e}', flush=True)
                counters['apply_failed'] += 1

    print('\n=== SUMMARY ===', flush=True)
    for k, v in sorted(counters.items()):
        print(f'  {k}: {v}', flush=True)
    print(f'\n{"APPLIED" if args.apply else "DRY-RUN complete. Run with --apply to write."}', flush=True)
    return 0


if __name__ == '__main__':
    with app.app_context():
        sys.exit(main())
