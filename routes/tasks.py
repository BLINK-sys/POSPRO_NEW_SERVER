"""
CRUD задач CRM + чек-лист + соисполнители/наблюдатели + activity.

Access matrix:
  admin       — видит и правит все задачи.
  system      — видит: свои (responsible=me) + где я co-worker/observer +
                где я creator. Правит: responsible=me ИЛИ member.role='co-worker'
                ИЛИ creator=me. observer — read-only.

Задача может быть привязана к сделке (`deal_id`) и/или клиенту (`client_id`).
Обе привязки опциональны — свободная задача разрешена.

Endpoints:
  GET    /api/admin/tasks                          list с фильтрами и пагинацией
  POST   /api/admin/tasks                          create
  GET    /api/admin/tasks/<id>                     details + members + checklist
  PUT    /api/admin/tasks/<id>                     update
  DELETE /api/admin/tasks/<id>                     delete

  POST   /api/admin/tasks/<id>/status              смена статуса + started_at/completed_at
  POST   /api/admin/tasks/<id>/members             invite co-worker/observer
  DELETE /api/admin/tasks/<id>/members/<user_id>   remove

  GET    /api/admin/tasks/<id>/checklist           список пунктов
  POST   /api/admin/tasks/<id>/checklist           add item
  PUT    /api/admin/tasks/<id>/checklist/<item_id> toggle done / rename
  DELETE /api/admin/tasks/<id>/checklist/<item_id> remove item
  POST   /api/admin/tasks/<id>/checklist/reorder   drag сортировка

  GET    /api/admin/tasks/<id>/activity            лента событий

Status-переходы триггерят обновления таймстампов:
  → in_progress  : started_at = NOW (если ещё не установлен)
  → done         : completed_at = NOW
  → pending/paused/waiting_check : сбрасывают completed_at (задача не финиш)
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from sqlalchemy import or_, and_

from extensions import db
from models.task import (
    Task, TaskMember, TaskChecklist, TaskActivity,
    TASK_PRIORITIES, TASK_STATUSES, TASK_MEMBER_ROLES,
)
from models.systemuser import SystemUser
from models.deal import Deal
from models.kp_client import KpClient


tasks_bp = Blueprint('tasks', __name__)


def _safe_notify(**kwargs):
    """Best-effort — сбой не валит основной путь. Ленивая загрузка сервиса."""
    try:
        from services.notifications import notify
        notify(**kwargs)
    except Exception as e:
        print(f'⚠️ notify failed: {e}', flush=True)


# ============================================================================
# Auth helpers
# ============================================================================

def _current_role_and_id() -> tuple[str | None, int | None]:
    claims = get_jwt() or {}
    role = claims.get('role')
    try:
        uid = int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        uid = None
    return role, uid


def _check_admin_or_system():
    role, _ = _current_role_and_id()
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _visible_tasks_query(role: str, user_id: int | None):
    """
    admin — все задачи. system — свои: creator=me ИЛИ responsible=me ИЛИ
    я в task_member.
    """
    q = Task.query
    if role == 'admin':
        return q
    if not user_id:
        return q.filter(db.text('1=0'))
    q = q.outerjoin(
        TaskMember,
        and_(TaskMember.task_id == Task.id, TaskMember.user_id == user_id),
    ).filter(or_(
        Task.creator_id == user_id,
        Task.responsible_id == user_id,
        TaskMember.id.isnot(None),
    )).distinct()
    return q


def _can_edit_task(task: Task, role: str, user_id: int | None) -> bool:
    """
    admin — правит любую.
    system — правит если responsible=me ИЛИ creator=me ИЛИ member.role='co-worker'.
    observer в task_member — read-only.
    """
    if role == 'admin':
        return True
    if not user_id:
        return False
    if task.responsible_id == user_id or task.creator_id == user_id:
        return True
    member = TaskMember.query.filter_by(task_id=task.id, user_id=user_id).first()
    return bool(member and member.role == 'co-worker')


# ============================================================================
# Serialization
# ============================================================================

def _task_full_dict(task: Task) -> dict:
    d = task.to_dict()
    members = TaskMember.query.filter_by(task_id=task.id).all()
    d['members'] = [
        {'id': m.id, 'user_id': m.user_id, 'role': m.role,
         'added_at': m.added_at.isoformat() if m.added_at else None}
        for m in members
    ]
    checklist = (
        TaskChecklist.query.filter_by(task_id=task.id)
        .order_by(TaskChecklist.order, TaskChecklist.id).all()
    )
    d['checklist'] = [
        {'id': c.id, 'text': c.text, 'done': bool(c.done), 'order': c.order}
        for c in checklist
    ]
    return d


# ============================================================================
# Валидация
# ============================================================================

def _parse_task_payload(data: dict, *, partial: bool = False):
    fields = {}

    title = (data.get('title') or '').strip() or None
    if not partial and not title:
        return False, 'Заголовок задачи обязателен', {}
    if title is not None:
        fields['title'] = title

    if 'description' in data:
        fields['description'] = data.get('description') or None

    if 'priority' in data:
        p = data.get('priority')
        if p and p not in TASK_PRIORITIES:
            return False, f'priority: {", ".join(TASK_PRIORITIES)}', {}
        if p:
            fields['priority'] = p

    if 'status' in data:
        s = data.get('status')
        if s and s not in TASK_STATUSES:
            return False, f'status: {", ".join(TASK_STATUSES)}', {}
        if s:
            fields['status'] = s

    for k in ('responsible_id', 'deal_id', 'client_id'):
        if k in data:
            v = data[k]
            if v is None or v == '':
                fields[k] = None
            else:
                try:
                    fields[k] = int(v)
                except (TypeError, ValueError):
                    return False, f'{k} должен быть числом', {}

    for k in ('due_at', 'started_at', 'completed_at'):
        if k in data:
            v = data.get(k)
            if not v:
                fields[k] = None
            else:
                try:
                    fields[k] = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
                except (TypeError, ValueError):
                    return False, f'{k} должен быть ISO8601', {}

    if 'tags' in data:
        tags = data.get('tags') or []
        if not isinstance(tags, list):
            return False, 'tags должны быть массивом', {}
        fields['tags'] = tags

    return True, None, fields


def _validate_refs(fields: dict):
    """Проверяет что responsible_id/deal_id/client_id существуют."""
    if fields.get('responsible_id'):
        if not SystemUser.query.get(fields['responsible_id']):
            return False, 'Ответственный не найден'
    if fields.get('deal_id'):
        if not Deal.query.get(fields['deal_id']):
            return False, 'Сделка не найдена'
    if fields.get('client_id'):
        if not KpClient.query.get(fields['client_id']):
            return False, 'Клиент не найден'
    return True, None


def _json_safe(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


# ============================================================================
# List / Get / Create / Update / Delete
# ============================================================================

@tasks_bp.route('/admin/tasks', methods=['GET'])
@jwt_required()
def list_tasks():
    """
    Список задач с фильтрами.

    Query params:
      status          — pending/in_progress/waiting_check/done/paused
      priority        — low/normal/high/urgent
      responsible_id  — задачи этого менеджера
      creator_id      — задачи созданные этим менеджером
      deal_id         — задачи привязанные к сделке
      client_id       — задачи привязанные к клиенту
      mine=1          — только мои (creator=me OR responsible=me)
      overdue=1       — просроченные (due_at < now AND status != done)
      q               — поиск по title
      limit / offset  — пагинация
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    q = _visible_tasks_query(role, user_id)

    status = request.args.get('status')
    priority = request.args.get('priority')
    responsible_id = request.args.get('responsible_id', type=int)
    creator_id = request.args.get('creator_id', type=int)
    deal_id = request.args.get('deal_id', type=int)
    client_id = request.args.get('client_id', type=int)
    mine = request.args.get('mine') == '1'
    overdue = request.args.get('overdue') == '1'
    search = (request.args.get('q') or '').strip()

    if status in TASK_STATUSES:
        q = q.filter(Task.status == status)
    if priority in TASK_PRIORITIES:
        q = q.filter(Task.priority == priority)
    if mine and user_id:
        q = q.filter(or_(Task.creator_id == user_id, Task.responsible_id == user_id))
    else:
        if responsible_id:
            q = q.filter(Task.responsible_id == responsible_id)
        if creator_id:
            q = q.filter(Task.creator_id == creator_id)
    if deal_id:
        q = q.filter(Task.deal_id == deal_id)
    if client_id:
        q = q.filter(Task.client_id == client_id)
    if overdue:
        q = q.filter(Task.due_at.isnot(None), Task.due_at < datetime.utcnow(), Task.status != 'done')
    if search:
        like = f'%{search.lower()}%'
        q = q.filter(db.func.lower(Task.title).like(like))

    total = q.count()
    limit = min(request.args.get('limit', 50, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)

    tasks = q.order_by(Task.updated_at.desc()).limit(limit).offset(offset).all()
    return jsonify({
        'success': True,
        'tasks': [t.to_dict() for t in tasks],
        'total': total,
        'limit': limit,
        'offset': offset,
    }), 200


@tasks_bp.route('/admin/tasks/<int:tid>', methods=['GET'])
@jwt_required()
def get_task(tid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    return jsonify({'success': True, 'task': _task_full_dict(t)}), 200


@tasks_bp.route('/admin/tasks', methods=['POST'])
@jwt_required()
def create_task():
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    data = request.get_json() or {}
    ok, msg, fields = _parse_task_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400
    ok, msg = _validate_refs(fields)
    if not ok:
        return jsonify({'error': msg}), 400

    # Постановщик — я. Ответственный по умолчанию — я (можно переопределить).
    responsible = fields.get('responsible_id', user_id)

    t = Task(
        title=fields['title'],
        description=fields.get('description'),
        priority=fields.get('priority', 'normal'),
        status=fields.get('status', 'pending'),
        creator_id=user_id,
        responsible_id=responsible,
        deal_id=fields.get('deal_id'),
        client_id=fields.get('client_id'),
        due_at=fields.get('due_at'),
        tags=fields.get('tags', []),
    )
    db.session.add(t)
    db.session.flush()

    db.session.add(TaskActivity(
        task_id=t.id, user_id=user_id, kind='created', payload={
            'responsible_id': responsible,
            'deal_id': t.deal_id, 'client_id': t.client_id,
            'due_at': _json_safe(t.due_at),
        },
    ))
    db.session.commit()

    # Автосоздание чата задачи + membership для creator и responsible.
    try:
        from models.chat import ChatRoom, ChatMember
        chat_room = ChatRoom(kind='task', related_task_id=t.id)
        db.session.add(chat_room)
        db.session.flush()
        seen: set[int] = set()
        for uid_ in (user_id, responsible):
            if uid_ and uid_ not in seen:
                db.session.add(ChatMember(room_id=chat_room.id, user_id=uid_))
                seen.add(uid_)
        db.session.commit()
    except Exception as e:
        print(f'⚠️ task chat auto-create failed for task {t.id}: {e}', flush=True)

    if responsible and responsible != user_id:
        _safe_notify(
            user_id=responsible, kind='task_assigned', section='tasks',
            entity_type='task', entity_id=t.id,
            payload={'task_title': t.title, 'assigned_by': user_id},
            push_title='Новая задача',
            push_body=t.title,
            push_url=f'/admin/tasks/{t.id}',
        )

    return jsonify({'success': True, 'task': _task_full_dict(t)}), 201


@tasks_bp.route('/admin/tasks/<int:tid>', methods=['PUT'])
@jwt_required()
def update_task(tid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав редактировать'}), 403

    data = request.get_json() or {}
    ok, msg, fields = _parse_task_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400
    ok, msg = _validate_refs(fields)
    if not ok:
        return jsonify({'error': msg}), 400

    # Смена статуса — через отдельный /status endpoint (там доп-логика
    # started_at/completed_at). PUT статус запрещён чтобы не обходить.
    if 'status' in fields and fields['status'] != t.status:
        return jsonify({'error': 'Смена статуса — через POST /tasks/<id>/status'}), 400

    changes = {}
    for k, v in fields.items():
        if k == 'status':
            continue
        old = getattr(t, k, None)
        if old != v:
            changes[k] = {'old': _json_safe(old), 'new': _json_safe(v)}
            setattr(t, k, v)

    t.updated_at = datetime.utcnow()

    if changes:
        if 'responsible_id' in changes:
            db.session.add(TaskActivity(
                task_id=t.id, user_id=user_id, kind='responsible_changed',
                payload=changes['responsible_id'],
            ))
        if 'due_at' in changes:
            db.session.add(TaskActivity(
                task_id=t.id, user_id=user_id, kind='due_at_changed',
                payload=changes['due_at'],
            ))
        other = {k: v for k, v in changes.items() if k not in ('responsible_id', 'due_at')}
        if other:
            db.session.add(TaskActivity(
                task_id=t.id, user_id=user_id, kind='field_changed',
                payload=other,
            ))

    db.session.commit()
    return jsonify({'success': True, 'task': _task_full_dict(t)}), 200


@tasks_bp.route('/admin/tasks/<int:tid>', methods=['DELETE'])
@jwt_required()
def delete_task(tid):
    """Удаление: admin любую, system — свою (creator=me ИЛИ responsible=me)."""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = Task.query.get(tid)
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if role != 'admin' and t.creator_id != user_id and t.responsible_id != user_id:
        return jsonify({'error': 'Нет прав удалить'}), 403

    db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Status transition
# ============================================================================

@tasks_bp.route('/admin/tasks/<int:tid>/status', methods=['POST'])
@jwt_required()
def change_task_status(tid):
    """
    Смена статуса + автоматическое обновление started_at / completed_at.

    Body: {"status": "in_progress" | "done" | ...}

    Правила:
    - При первом переходе в 'in_progress' ставим `started_at=now`.
      Повторные переходы (paused → in_progress) не перезаписывают.
    - Переход в 'done' ставит `completed_at=now`.
    - Любой не-done статус сбрасывает `completed_at=NULL` (задача не финиш).
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав редактировать'}), 403

    data = request.get_json() or {}
    new_status = data.get('status')
    if new_status not in TASK_STATUSES:
        return jsonify({'error': f'status: {", ".join(TASK_STATUSES)}'}), 400

    if new_status == t.status:
        return jsonify({'success': True, 'task': _task_full_dict(t)}), 200

    from_status = t.status
    now = datetime.utcnow()

    if new_status == 'in_progress' and t.started_at is None:
        t.started_at = now
    if new_status == 'done':
        t.completed_at = now
    else:
        t.completed_at = None

    t.status = new_status
    t.updated_at = now

    db.session.add(TaskActivity(
        task_id=t.id, user_id=user_id, kind='status_changed',
        payload={'from': from_status, 'to': new_status},
    ))
    db.session.commit()

    # Уведомляем постановщика (если это не он менял) — статус его задачи
    # изменился. Ответственного не уведомляем, он сам менял (обычно).
    if t.creator_id and t.creator_id != user_id:
        _safe_notify(
            user_id=t.creator_id, kind='task_status_changed', section='tasks',
            entity_type='task', entity_id=t.id,
            payload={'task_title': t.title, 'from': from_status, 'to': new_status},
            push_title='Статус задачи изменён',
            push_body=f'{t.title}: {new_status}',
            push_url=f'/admin/tasks/{t.id}',
        )

    return jsonify({'success': True, 'task': _task_full_dict(t)}), 200


# ============================================================================
# Members
# ============================================================================

@tasks_bp.route('/admin/tasks/<int:tid>/members', methods=['POST'])
@jwt_required()
def add_task_member(tid):
    """Body: {"user_id": N, "role": "co-worker" | "observer"}"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    data = request.get_json() or {}
    try:
        target_uid = int(data['user_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'user_id обязателен'}), 400
    member_role = data.get('role') or 'co-worker'
    if member_role not in TASK_MEMBER_ROLES:
        return jsonify({'error': f'role: {", ".join(TASK_MEMBER_ROLES)}'}), 400

    if not SystemUser.query.get(target_uid):
        return jsonify({'error': 'Пользователь не найден'}), 404
    if target_uid == t.responsible_id:
        return jsonify({'error': 'Ответственный уже имеет полный доступ'}), 400

    exists = TaskMember.query.filter_by(task_id=tid, user_id=target_uid).first()
    if exists:
        if exists.role != member_role:
            exists.role = member_role
            db.session.commit()
        return jsonify({'success': True, 'member': {
            'id': exists.id, 'user_id': exists.user_id, 'role': exists.role,
        }}), 200

    m = TaskMember(task_id=tid, user_id=target_uid, role=member_role)
    db.session.add(m)
    db.session.add(TaskActivity(
        task_id=tid, user_id=user_id, kind='member_added',
        payload={'user_id': target_uid, 'role': member_role},
    ))
    db.session.commit()

    # Синк chat-membership для чата задачи.
    try:
        from models.chat import ChatRoom, ChatMember
        chat_room = ChatRoom.query.filter_by(kind='task', related_task_id=tid).first()
        if chat_room and not ChatMember.query.filter_by(
            room_id=chat_room.id, user_id=target_uid
        ).first():
            db.session.add(ChatMember(room_id=chat_room.id, user_id=target_uid))
            db.session.commit()
    except Exception as e:
        print(f'⚠️ task chat member sync failed: {e}', flush=True)

    _safe_notify(
        user_id=target_uid, kind='task_member_added', section='tasks',
        entity_type='task', entity_id=tid,
        payload={'task_title': t.title, 'role': member_role, 'added_by': user_id},
        push_title='Вас добавили в задачу',
        push_body=f'{t.title} ({"наблюдатель" if member_role == "observer" else "соисполнитель"})',
        push_url=f'/admin/tasks/{tid}',
    )

    return jsonify({'success': True, 'member': {
        'id': m.id, 'user_id': m.user_id, 'role': m.role,
    }}), 201


@tasks_bp.route('/admin/tasks/<int:tid>/members/<int:uid>', methods=['DELETE'])
@jwt_required()
def remove_task_member(tid, uid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    m = TaskMember.query.filter_by(task_id=tid, user_id=uid).first()
    if not m:
        return jsonify({'error': 'Участник не найден'}), 404

    removed_role = m.role
    db.session.delete(m)
    db.session.add(TaskActivity(
        task_id=tid, user_id=user_id, kind='member_removed',
        payload={'user_id': uid, 'role': removed_role},
    ))
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Checklist
# ============================================================================

@tasks_bp.route('/admin/tasks/<int:tid>/checklist', methods=['GET'])
@jwt_required()
def list_checklist(tid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404

    items = (
        TaskChecklist.query.filter_by(task_id=tid)
        .order_by(TaskChecklist.order, TaskChecklist.id).all()
    )
    return jsonify({
        'success': True,
        'checklist': [
            {'id': c.id, 'text': c.text, 'done': bool(c.done), 'order': c.order}
            for c in items
        ],
    }), 200


@tasks_bp.route('/admin/tasks/<int:tid>/checklist', methods=['POST'])
@jwt_required()
def add_checklist_item(tid):
    """Body: {"text": "..."}"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'text обязателен'}), 400
    if len(text) > 500:
        return jsonify({'error': 'text слишком длинный (макс 500)'}), 400

    max_order = db.session.query(
        db.func.coalesce(db.func.max(TaskChecklist.order), -1)
    ).filter_by(task_id=tid).scalar()

    item = TaskChecklist(task_id=tid, text=text, done=False, order=int(max_order) + 1)
    db.session.add(item)
    db.session.add(TaskActivity(
        task_id=tid, user_id=user_id, kind='checklist_added',
        payload={'text': text},
    ))
    db.session.commit()
    return jsonify({'success': True, 'item': {
        'id': item.id, 'text': item.text, 'done': bool(item.done), 'order': item.order,
    }}), 201


@tasks_bp.route('/admin/tasks/<int:tid>/checklist/<int:iid>', methods=['PUT'])
@jwt_required()
def update_checklist_item(tid, iid):
    """Body: {"text": "..."} и/или {"done": bool}"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    item = TaskChecklist.query.filter_by(id=iid, task_id=tid).first()
    if not item:
        return jsonify({'error': 'Пункт не найден'}), 404

    data = request.get_json() or {}
    activity_kind = None
    if 'done' in data:
        new_done = bool(data['done'])
        if item.done != new_done:
            item.done = new_done
            activity_kind = 'checklist_toggled'
    if 'text' in data:
        new_text = (data.get('text') or '').strip()
        if not new_text:
            return jsonify({'error': 'text не может быть пустым'}), 400
        if len(new_text) > 500:
            return jsonify({'error': 'text слишком длинный (макс 500)'}), 400
        item.text = new_text

    if activity_kind:
        db.session.add(TaskActivity(
            task_id=tid, user_id=user_id, kind=activity_kind,
            payload={'item_id': item.id, 'done': bool(item.done), 'text': item.text},
        ))

    db.session.commit()
    return jsonify({'success': True, 'item': {
        'id': item.id, 'text': item.text, 'done': bool(item.done), 'order': item.order,
    }}), 200


@tasks_bp.route('/admin/tasks/<int:tid>/checklist/<int:iid>', methods=['DELETE'])
@jwt_required()
def delete_checklist_item(tid, iid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    item = TaskChecklist.query.filter_by(id=iid, task_id=tid).first()
    if not item:
        return jsonify({'error': 'Пункт не найден'}), 404

    text = item.text
    db.session.delete(item)
    db.session.add(TaskActivity(
        task_id=tid, user_id=user_id, kind='checklist_removed',
        payload={'text': text},
    ))
    db.session.commit()
    return jsonify({'success': True}), 200


@tasks_bp.route('/admin/tasks/<int:tid>/checklist/reorder', methods=['POST'])
@jwt_required()
def reorder_checklist(tid):
    """Body: [{id, order}, ...]"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404
    if not _can_edit_task(t, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    payload = request.get_json()
    if not isinstance(payload, list):
        return jsonify({'error': 'Ожидался массив {id, order}'}), 400

    ids = [item.get('id') for item in payload if isinstance(item, dict)]
    items = {c.id: c for c in TaskChecklist.query.filter(
        TaskChecklist.id.in_(ids), TaskChecklist.task_id == tid
    ).all()}

    for entry in payload:
        if not isinstance(entry, dict):
            continue
        iid = entry.get('id')
        order = entry.get('order')
        if iid in items and isinstance(order, int):
            items[iid].order = order

    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Activity
# ============================================================================

@tasks_bp.route('/admin/tasks/<int:tid>/activity', methods=['GET'])
@jwt_required()
def task_activity(tid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return jsonify({'error': 'Задача не найдена'}), 404

    limit = min(request.args.get('limit', 50, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)

    items = (
        TaskActivity.query.filter_by(task_id=tid)
        .order_by(TaskActivity.created_at.desc())
        .limit(limit).offset(offset).all()
    )
    return jsonify({
        'success': True,
        'activity': [
            {'id': a.id, 'task_id': a.task_id, 'user_id': a.user_id,
             'kind': a.kind, 'payload': a.payload or {},
             'created_at': a.created_at.isoformat() if a.created_at else None}
            for a in items
        ],
        'limit': limit,
        'offset': offset,
    }), 200
