"""
CRUD-ручки для модуля «Проекты» с собственным канбаном.

Проект — верхнеуровневый контейнер для задач с участниками и своим
набором стадий. См. models/project.py.

Endpoints (под `/api/admin`):
  GET    /projects                           список активных (+ q, status)
  POST   /projects                           создать (авто: 4 стадии + owner в members)
  GET    /projects/<pid>                     полное: project + members + stages
  PUT    /projects/<pid>                     name/color/description/status/owner_id
  DELETE /projects/<pid>                     удалить (задачи остаются)

  POST   /projects/<pid>/archive             status=archived
  POST   /projects/<pid>/unarchive           status=active

  GET    /projects/<pid>/stages              колонки канбана
  POST   /projects/<pid>/stages              создать (авто maps_to_status
                                             по позиции: 1я=pending, последняя=done,
                                             иначе in_progress)
  PUT    /projects/<pid>/stages/<sid>        name/color/maps_to_status/sort_order
  DELETE /projects/<pid>/stages/<sid>        удалить (задачи этой колонки → NULL)
  POST   /projects/<pid>/stages/reorder      {order: [sid, sid, ...]}

  GET    /projects/<pid>/members             участники с ролями
  POST   /projects/<pid>/members             {user_id, role}
  PUT    /projects/<pid>/members/<mid>       {role}
  DELETE /projects/<pid>/members/<mid>

  GET    /projects/<pid>/tasks               все задачи проекта (для канбана/списка)
  POST   /projects/<pid>/tasks/<tid>/move    {stage_id} — DnD-перенос.
                                             Автомап status по stage.maps_to_status.
                                             Сохраняет prev_project_stage_id.

Auth: admin/system обязательно. Настройка (создание/правки стадий,
участников, статуса, владельца) — только can_manage_projects или owner
проекта.
"""

from __future__ import annotations

import re
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models.project import (
    Project, ProjectMember, ProjectStage, PROJECT_STAGE_STATUS_VALUES,
)
from models.task import Task
from models.systemuser import SystemUser


projects_bp = Blueprint('projects', __name__)


HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# Шаблон стадий при создании нового проекта. Идея: сразу покрыть все
# частотные статусы, чтобы при первом автомапе было куда положить задачу.
# Юзер потом переименует/добавит/удалит в настройках проекта.
DEFAULT_STAGES = [
    {'name': 'К выполнению', 'color': '#94a3b8', 'maps_to_status': 'pending'},
    {'name': 'В работе',      'color': '#60a5fa', 'maps_to_status': 'in_progress'},
    {'name': 'На проверке',   'color': '#f59e0b', 'maps_to_status': 'waiting_check'},
    {'name': 'Готово',        'color': '#10b981', 'maps_to_status': 'done'},
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _check_admin_or_system():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _current_user_id() -> int | None:
    try:
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        return None


def _can_manage_project(project: Project | None) -> bool:
    """
    Может ли текущий пользователь настраивать именно этот проект?
    Правила:
      - is_owner или can_manage_projects → да, любой проект.
      - Владелец конкретного проекта (project.owner_id == me) → да.
      - Иначе — нет.
    """
    from services.perms import is_owner as _is_owner
    from services.perms import can_manage_projects as _cmp
    uid = _current_user_id()
    if not uid:
        return False
    if _is_owner(uid) or _cmp(uid):
        return True
    if project and project.owner_id == uid:
        return True
    return False


def _check_can_manage_projects_global():
    """
    Создание нового проекта и глобальные настройки доступны только
    can_manage_projects/owner.
    """
    from services.perms import is_owner as _is_owner
    from services.perms import can_manage_projects as _cmp
    uid = _current_user_id()
    if not (_is_owner(uid) or _cmp(uid)):
        return jsonify({'error': 'Управление проектами доступно только владельцу'}), 403
    return None


def _check_project_access(project: Project) -> tuple[bool, str]:
    """
    Может ли юзер ХОТЯ БЫ видеть проект (без права настраивать).
    True если он owner/can_manage_projects/project.owner/один из участников.
    Возвращает (allowed, scope) где scope = 'manage' | 'view'.
    """
    from services.perms import is_owner as _is_owner
    from services.perms import can_manage_projects as _cmp
    uid = _current_user_id()
    if not uid:
        return False, 'none'
    if _is_owner(uid) or _cmp(uid):
        return True, 'manage'
    if project.owner_id == uid:
        return True, 'manage'
    m = ProjectMember.query.filter_by(project_id=project.id, user_id=uid).first()
    if m:
        return True, 'view'
    return False, 'none'


def _parse_payload(data: dict, *, partial: bool = False):
    fields: dict = {}

    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название проекта обязательно', {}
    if name is not None:
        if len(name) > 255:
            return False, 'Название слишком длинное (макс 255)', {}
        fields['name'] = name

    if 'color' in data:
        color = (data.get('color') or '').strip() or '#facc15'
        if not HEX_RE.match(color):
            return False, 'color должен быть в формате #RRGGBB', {}
        fields['color'] = color

    if 'description' in data:
        desc = data.get('description')
        fields['description'] = (desc or '').strip() or None

    if 'status' in data:
        st = (data.get('status') or 'active').strip()
        if st not in ('active', 'archived'):
            return False, 'status должен быть active или archived', {}
        fields['status'] = st

    if 'owner_id' in data:
        raw = data.get('owner_id')
        if raw is None or raw == '':
            fields['owner_id'] = None
        else:
            try:
                fields['owner_id'] = int(raw)
            except (TypeError, ValueError):
                return False, 'owner_id должен быть числом', {}

    return True, None, fields


def _default_stage_map_for(position: int, total: int) -> str:
    """
    Авто-mapping для новой колонки по её позиции в наборе.
    Первая — pending, последняя — done, остальные — in_progress.
    total — ожидаемое число колонок после вставки.
    """
    if total <= 1:
        return 'pending'
    if position == 0:
        return 'pending'
    if position == total - 1:
        return 'done'
    return 'in_progress'


def _serialize_project_full(p: Project) -> dict:
    out = p.to_dict()
    out['members'] = [m.to_dict() for m in
                      ProjectMember.query.filter_by(project_id=p.id).all()]
    out['stages'] = [
        s.to_dict() for s in
        ProjectStage.query.filter_by(project_id=p.id)
        .order_by(ProjectStage.sort_order, ProjectStage.id).all()
    ]
    out['task_count'] = int(
        db.session.query(db.func.count(Task.id))
        .filter(Task.project_id == p.id).scalar() or 0
    )
    return out


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------

@projects_bp.route('/admin/projects', methods=['GET'])
@jwt_required()
def list_projects():
    err = _check_admin_or_system()
    if err:
        return err

    q = (request.args.get('q') or '').strip().lower()
    status = (request.args.get('status') or 'active').strip()
    query = Project.query
    if status in ('active', 'archived'):
        query = query.filter(Project.status == status)
    if q:
        query = query.filter(db.func.lower(Project.name).like(f'%{q}%'))
    projects = query.order_by(Project.name.asc()).all()

    counts = dict(
        db.session.query(Task.project_id, db.func.count(Task.id))
        .filter(Task.project_id.isnot(None))
        .group_by(Task.project_id)
        .all()
    )
    out = []
    for p in projects:
        row = p.to_dict()
        row['task_count'] = int(counts.get(p.id, 0))
        out.append(row)

    return jsonify({'success': True, 'projects': out}), 200


@projects_bp.route('/admin/projects', methods=['POST'])
@jwt_required()
def create_project():
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage_projects_global()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    dup = Project.query.filter(
        db.func.lower(Project.name) == fields['name'].lower(),
    ).first()
    if dup:
        return jsonify({'error': 'Проект с таким названием уже существует'}), 409

    me = _current_user_id()
    p = Project(
        name=fields['name'],
        color=fields.get('color', '#facc15'),
        description=fields.get('description'),
        status=fields.get('status', 'active'),
        owner_id=fields.get('owner_id', me),
        created_by=me,
    )
    db.session.add(p)
    db.session.flush()

    # Автодефолтные стадии.
    for i, st in enumerate(DEFAULT_STAGES):
        db.session.add(ProjectStage(
            project_id=p.id,
            name=st['name'],
            color=st['color'],
            sort_order=i,
            maps_to_status=st['maps_to_status'],
        ))

    # Владелец автоматически попадает в участники как owner.
    if p.owner_id:
        db.session.add(ProjectMember(
            project_id=p.id, user_id=p.owner_id, role='owner',
        ))

    db.session.commit()
    return jsonify({'success': True, 'project': _serialize_project_full(p)}), 201


@projects_bp.route('/admin/projects/<int:pid>', methods=['GET'])
@jwt_required()
def get_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    allowed, _scope = _check_project_access(p)
    if not allowed:
        return jsonify({'error': 'Нет доступа к проекту'}), 403
    return jsonify({'success': True, 'project': _serialize_project_full(p)}), 200


@projects_bp.route('/admin/projects/<int:pid>', methods=['PUT'])
@jwt_required()
def update_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав на настройку этого проекта'}), 403

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in fields and fields['name'].lower() != (p.name or '').lower():
        dup = Project.query.filter(
            db.func.lower(Project.name) == fields['name'].lower(),
            Project.id != pid,
        ).first()
        if dup:
            return jsonify({'error': 'Проект с таким названием уже существует'}), 409

    for k, v in fields.items():
        setattr(p, k, v)
    db.session.commit()
    return jsonify({'success': True, 'project': _serialize_project_full(p)}), 200


@projects_bp.route('/admin/projects/<int:pid>', methods=['DELETE'])
@jwt_required()
def delete_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав на удаление проекта'}), 403
    db.session.delete(p)
    db.session.commit()
    return jsonify({'success': True}), 200


@projects_bp.route('/admin/projects/<int:pid>/archive', methods=['POST'])
@jwt_required()
def archive_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    p.status = 'archived'
    db.session.commit()
    return jsonify({'success': True, 'project': p.to_dict()}), 200


@projects_bp.route('/admin/projects/<int:pid>/unarchive', methods=['POST'])
@jwt_required()
def unarchive_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    p.status = 'active'
    db.session.commit()
    return jsonify({'success': True, 'project': p.to_dict()}), 200


# ---------------------------------------------------------------------------
# Stages CRUD
# ---------------------------------------------------------------------------

@projects_bp.route('/admin/projects/<int:pid>/stages', methods=['GET'])
@jwt_required()
def list_stages(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    allowed, _ = _check_project_access(p)
    if not allowed:
        return jsonify({'error': 'Нет доступа'}), 403
    stages = (
        ProjectStage.query.filter_by(project_id=pid)
        .order_by(ProjectStage.sort_order, ProjectStage.id).all()
    )
    return jsonify({'stages': [s.to_dict() for s in stages]}), 200


@projects_bp.route('/admin/projects/<int:pid>/stages', methods=['POST'])
@jwt_required()
def create_stage(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name обязателен'}), 400
    color = (data.get('color') or '#94a3b8').strip()
    if not HEX_RE.match(color):
        return jsonify({'error': 'color должен быть в формате #RRGGBB'}), 400

    existing = (
        ProjectStage.query.filter_by(project_id=pid)
        .order_by(ProjectStage.sort_order.desc()).all()
    )
    next_order = (existing[0].sort_order + 1) if existing else 0

    maps_to = data.get('maps_to_status')
    if not maps_to:
        maps_to = _default_stage_map_for(len(existing), len(existing) + 1)
    if maps_to not in PROJECT_STAGE_STATUS_VALUES:
        return jsonify({'error': f'maps_to_status должен быть один из {PROJECT_STAGE_STATUS_VALUES}'}), 400

    s = ProjectStage(
        project_id=pid, name=name, color=color,
        sort_order=next_order, maps_to_status=maps_to,
    )
    db.session.add(s)
    db.session.commit()
    return jsonify({'stage': s.to_dict()}), 201


@projects_bp.route('/admin/projects/<int:pid>/stages/<int:sid>', methods=['PUT'])
@jwt_required()
def update_stage(pid, sid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    s = ProjectStage.query.filter_by(id=sid, project_id=pid).first()
    if not s:
        return jsonify({'error': 'Колонка не найдена'}), 404

    data = request.get_json() or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name не может быть пустым'}), 400
        s.name = name
    if 'color' in data:
        color = (data.get('color') or '').strip()
        if not HEX_RE.match(color):
            return jsonify({'error': 'color должен быть в формате #RRGGBB'}), 400
        s.color = color
    if 'maps_to_status' in data:
        v = data.get('maps_to_status')
        if v not in PROJECT_STAGE_STATUS_VALUES:
            return jsonify({'error': f'maps_to_status должен быть один из {PROJECT_STAGE_STATUS_VALUES}'}), 400
        s.maps_to_status = v
    if 'sort_order' in data:
        try:
            s.sort_order = int(data['sort_order'])
        except (TypeError, ValueError):
            return jsonify({'error': 'sort_order должен быть числом'}), 400

    db.session.commit()
    return jsonify({'stage': s.to_dict()}), 200


@projects_bp.route('/admin/projects/<int:pid>/stages/<int:sid>', methods=['DELETE'])
@jwt_required()
def delete_stage(pid, sid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    s = ProjectStage.query.filter_by(id=sid, project_id=pid).first()
    if not s:
        return jsonify({'error': 'Колонка не найдена'}), 404

    db.session.delete(s)   # task.project_stage_id → NULL по FK
    db.session.commit()
    return jsonify({'success': True}), 200


@projects_bp.route('/admin/projects/<int:pid>/stages/reorder', methods=['POST'])
@jwt_required()
def reorder_stages(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    data = request.get_json() or {}
    order = data.get('order') or []
    if not isinstance(order, list):
        return jsonify({'error': 'order должен быть массивом id'}), 400
    stages = {
        s.id: s for s in
        ProjectStage.query.filter_by(project_id=pid).all()
    }
    for idx, sid in enumerate(order):
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            continue
        s = stages.get(sid_int)
        if s:
            s.sort_order = idx
    db.session.commit()
    return jsonify({'success': True}), 200


# ---------------------------------------------------------------------------
# Members CRUD
# ---------------------------------------------------------------------------

@projects_bp.route('/admin/projects/<int:pid>/members', methods=['GET'])
@jwt_required()
def list_members(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    allowed, _ = _check_project_access(p)
    if not allowed:
        return jsonify({'error': 'Нет доступа'}), 403
    members = ProjectMember.query.filter_by(project_id=pid).all()
    return jsonify({'members': [m.to_dict() for m in members]}), 200


@projects_bp.route('/admin/projects/<int:pid>/members', methods=['POST'])
@jwt_required()
def add_member(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    data = request.get_json() or {}
    try:
        uid = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'user_id обязателен'}), 400
    role = (data.get('role') or 'member').strip()
    if role not in ('owner', 'member', 'observer'):
        return jsonify({'error': 'role должен быть owner/member/observer'}), 400

    if not SystemUser.query.get(uid):
        return jsonify({'error': 'Пользователь не найден'}), 404

    existing = ProjectMember.query.filter_by(
        project_id=pid, user_id=uid,
    ).first()
    if existing:
        existing.role = role
        db.session.commit()
        return jsonify({'member': existing.to_dict()}), 200

    m = ProjectMember(project_id=pid, user_id=uid, role=role)
    db.session.add(m)
    db.session.commit()
    return jsonify({'member': m.to_dict()}), 201


@projects_bp.route('/admin/projects/<int:pid>/members/<int:mid>', methods=['PUT'])
@jwt_required()
def update_member(pid, mid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    m = ProjectMember.query.filter_by(id=mid, project_id=pid).first()
    if not m:
        return jsonify({'error': 'Участник не найден'}), 404
    data = request.get_json() or {}
    role = (data.get('role') or '').strip()
    if role not in ('owner', 'member', 'observer'):
        return jsonify({'error': 'role должен быть owner/member/observer'}), 400
    m.role = role
    db.session.commit()
    return jsonify({'member': m.to_dict()}), 200


@projects_bp.route('/admin/projects/<int:pid>/members/<int:mid>', methods=['DELETE'])
@jwt_required()
def remove_member(pid, mid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    if not _can_manage_project(p):
        return jsonify({'error': 'Нет прав'}), 403
    m = ProjectMember.query.filter_by(id=mid, project_id=pid).first()
    if not m:
        return jsonify({'error': 'Участник не найден'}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True}), 200


# ---------------------------------------------------------------------------
# Tasks of a project + move
# ---------------------------------------------------------------------------

@projects_bp.route('/admin/projects/<int:pid>/tasks', methods=['GET'])
@jwt_required()
def project_tasks(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    allowed, _ = _check_project_access(p)
    if not allowed:
        return jsonify({'error': 'Нет доступа'}), 403
    tasks = (
        Task.query.filter_by(project_id=pid)
        .order_by(Task.created_at.desc()).all()
    )
    return jsonify({'tasks': [t.to_dict() for t in tasks]}), 200


@projects_bp.route('/admin/projects/<int:pid>/tasks/<int:tid>/move', methods=['POST'])
@jwt_required()
def move_task_to_stage(pid, tid):
    """
    DnD-перенос задачи в другую колонку канбана.
    Body: {"stage_id": N}  (N=null → снять со всех колонок)

    Автомап: если maps_to_status новой колонки отличается от текущего
    task.status — задача получает новый статус.
    В prev_project_stage_id сохраняется предыдущая колонка (для «вернуться»
    при отмене автомапа).
    """
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404
    allowed, _ = _check_project_access(p)
    if not allowed:
        return jsonify({'error': 'Нет доступа'}), 403
    t = Task.query.get(tid)
    if not t or t.project_id != pid:
        return jsonify({'error': 'Задача не в этом проекте'}), 404

    data = request.get_json() or {}
    raw = data.get('stage_id')
    stage = None
    if raw is not None and raw != '':
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'stage_id должен быть числом'}), 400
        stage = ProjectStage.query.filter_by(id=sid, project_id=pid).first()
        if not stage:
            return jsonify({'error': 'Колонка не найдена'}), 404

    old_stage_id = t.project_stage_id
    t.prev_project_stage_id = old_stage_id if old_stage_id else None
    t.project_stage_id = stage.id if stage else None

    # Автомап статуса — если колонка и у неё другой maps_to_status.
    if stage and stage.maps_to_status and stage.maps_to_status != t.status:
        t.status = stage.maps_to_status
        if stage.maps_to_status == 'done' and not t.completed_at:
            t.completed_at = datetime.utcnow()
        elif stage.maps_to_status != 'done':
            t.completed_at = None
        if stage.maps_to_status == 'in_progress' and not t.started_at:
            t.started_at = datetime.utcnow()

    db.session.commit()
    return jsonify({'success': True, 'task': t.to_dict()}), 200
