"""
Endpoints для записи и чтения AI-логов.

Запись (write API, вызывается AI-фичами в процессе работы):
    POST   /api/ai-import-logs                — лог попытки импорта товара
    PATCH  /api/ai-import-logs/<id>           — обновить статус (saved + product_id)
    POST   /api/ai-chat-logs/messages         — добавить пару сообщений в чат-сессию
                                                 (создаёт сессию если её нет)

Чтение (admin API, доступен только тем кто видит вкладку AI настройки):
    GET    /api/admin/ai-logs/imports         — список логов импорта с фильтрами
    GET    /api/admin/ai-logs/chats           — список чат-сессий с фильтрами
    GET    /api/admin/ai-logs/chats/<id>      — полная переписка одной сессии
    GET    /api/admin/ai-logs/system-users    — список системных пользователей,
                                                 у которых хоть раз были логи
                                                 (для фильтра «конкретный юзер»)
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from sqlalchemy import desc, or_

from extensions import db
from models.ai_logs import (
    AIImportLog, AIChatSession, AIChatMessage,
    IMPORT_STATUS_ERROR, IMPORT_STATUS_IMPORTED, IMPORT_STATUS_SAVED,
    generate_session_token,
)
from models.ai_consultant_access import AIConsultantAccess
from routes.ai_consultant_access import _resolve_viewer, _has_settings_admin_access


ai_logs_bp = Blueprint('ai_logs', __name__)


_VALID_IMPORT_STATUSES = {IMPORT_STATUS_ERROR, IMPORT_STATUS_IMPORTED, IMPORT_STATUS_SAVED}
_VALID_USER_ROLES = {'guest', 'client', 'wholesale', 'system', 'admin'}
_VALID_MESSAGE_ROLES = {'user', 'assistant'}


def _admin_required():
    """Гард для админских GET-эндпоинтов. Возвращает (viewer, error_response).
    Если viewer допущен к разделу — error_response = None."""
    viewer = _resolve_viewer()
    settings = AIConsultantAccess.get_or_create()
    if not _has_settings_admin_access(viewer, settings):
        return None, (jsonify({'error': 'Доступ к логам не выдан'}), 403)
    return viewer, None


# ────────────────────────────────────────────────────────────────────────
# Write API: импорт товаров
# ────────────────────────────────────────────────────────────────────────

@ai_logs_bp.route('/ai-import-logs', methods=['POST'])
def create_import_log():
    """
    Создаёт строку лога импорта. Вызывается из routes/product_auto_fill.py
    после попытки парсинга — успешной или нет.

    Body:
      source_url    str   обязательно
      status        str   'error' | 'imported' | 'saved'
      imported_data dict  опц., что AI вытащил
      error_message str   опц., при status=error
      user_id       int   опц., если зовём из контекста с известным user
      user_email    str   обязательно — для денормализации
      user_role     str   опц., default 'system'

    Возвращает {id} — фронт сохранит у себя, чтобы потом обновить статус
    после реального сохранения товара.
    """
    body = request.get_json(silent=True) or {}

    source_url = (body.get('source_url') or '').strip()
    if not source_url:
        return jsonify({'error': 'source_url обязателен'}), 400

    status = body.get('status') or IMPORT_STATUS_ERROR
    if status not in _VALID_IMPORT_STATUSES:
        return jsonify({'error': f'status должен быть одним из {sorted(_VALID_IMPORT_STATUSES)}'}), 400

    user_email = (body.get('user_email') or '').strip()
    if not user_email:
        return jsonify({'error': 'user_email обязателен'}), 400

    log = AIImportLog(
        user_id=body.get('user_id'),
        user_email=user_email,
        user_role=(body.get('user_role') or 'system'),
        source_url=source_url,
        status=status,
        imported_data=body.get('imported_data'),
        error_message=body.get('error_message'),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(log.to_dict()), 201


@ai_logs_bp.route('/ai-import-logs/<int:log_id>', methods=['PATCH'])
def update_import_log(log_id):
    """
    Дописывает информацию о реальном сохранении товара в магазине:
    выставляет status='saved', product_id, product_name. Вызывается
    после finalize товара, который был создан из AI-импорта.
    """
    log = AIImportLog.query.get_or_404(log_id)
    body = request.get_json(silent=True) or {}

    if 'status' in body:
        if body['status'] not in _VALID_IMPORT_STATUSES:
            return jsonify({'error': 'недопустимый status'}), 400
        log.status = body['status']

    if 'product_id' in body:
        log.product_id = body['product_id']
    if 'product_name' in body:
        log.product_name = body['product_name']
    if 'error_message' in body:
        log.error_message = body['error_message']

    log.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(log.to_dict())


# ────────────────────────────────────────────────────────────────────────
# Write API: чат
# ────────────────────────────────────────────────────────────────────────

@ai_logs_bp.route('/ai-chat-logs/messages', methods=['POST'])
def append_chat_messages():
    """
    Добавляет одно или несколько сообщений в чат-сессию. Если сессии с
    указанным client_session_token ещё нет — создаёт.

    Доступно без авторизации (для гостей). Профиль юзера определяется
    из JWT если есть, иначе сессия помечается как 'guest'.

    Body:
      session_token  str    UUID сессии от клиента (хранится в localStorage)
      messages       list   [{role: 'user'|'assistant', content: str}, ...]
    """
    body = request.get_json(silent=True) or {}

    token = (body.get('session_token') or '').strip()
    if not token:
        token = generate_session_token()

    messages = body.get('messages') or []
    if not isinstance(messages, list) or not messages:
        return jsonify({'error': 'messages должен быть непустым массивом'}), 400

    # Валидация и нормализация сообщений
    cleaned = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = (m.get('role') or '').strip().lower()
        content = (m.get('content') or '').strip()
        if role not in _VALID_MESSAGE_ROLES or not content:
            continue
        cleaned.append((role, content))
    if not cleaned:
        return jsonify({'error': 'нет валидных сообщений в payload'}), 400

    # Найти или создать сессию. Профиль юзера фиксируем при создании;
    # если потом юзер залогинится — сессия останется с прежней меткой,
    # но это редкий кейс (обычно юзер открывает чат уже под своим юзером).
    session = AIChatSession.query.filter_by(client_session_token=token).first()
    if session is None:
        viewer = _resolve_viewer()
        # Подтянем имя если это клиент из таблицы users
        user_name = None
        if viewer['kind'] in ('client', 'wholesale') and viewer.get('user_id'):
            from models.user import User
            u = User.query.get(viewer['user_id'])
            if u:
                user_name = (u.full_name or u.ip_name or u.too_name or u.email)
        elif viewer['kind'] in ('system', 'admin') and viewer.get('user_id'):
            from models.systemuser import SystemUser
            su = SystemUser.query.get(viewer['user_id'])
            if su:
                user_name = su.full_name or su.email
        session = AIChatSession(
            client_session_token=token,
            user_role=viewer['kind'],
            user_id=viewer.get('user_id'),
            user_email=viewer.get('email'),
            user_name=user_name,
            message_count=0,
        )
        db.session.add(session)
        db.session.flush()  # получаем session.id

    # Добавляем сообщения
    now = datetime.utcnow()
    for role, content in cleaned:
        msg = AIChatMessage(
            session_id=session.id,
            role=role,
            content=content,
            created_at=now,
        )
        db.session.add(msg)

    session.message_count += len(cleaned)
    session.last_message_at = now
    db.session.commit()

    return jsonify({
        'session_id': session.id,
        'session_token': session.client_session_token,
        'message_count': session.message_count,
        'added': len(cleaned),
    }), 201


# ────────────────────────────────────────────────────────────────────────
# Admin GET API: импорт
# ────────────────────────────────────────────────────────────────────────

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


@ai_logs_bp.route('/admin/ai-logs/imports', methods=['GET'])
def list_import_logs():
    _, err = _admin_required()
    if err:
        return err

    q = AIImportLog.query

    # Фильтры
    status = request.args.get('status')
    if status and status in _VALID_IMPORT_STATUSES:
        q = q.filter(AIImportLog.status == status)

    user_id = request.args.get('user_id', type=int)
    if user_id:
        q = q.filter(AIImportLog.user_id == user_id)

    user_role = request.args.get('user_role')
    if user_role and user_role in _VALID_USER_ROLES:
        q = q.filter(AIImportLog.user_role == user_role)

    date_from = _parse_date(request.args.get('date_from'))
    if date_from:
        q = q.filter(AIImportLog.created_at >= date_from)
    date_to = _parse_date(request.args.get('date_to'))
    if date_to:
        # включающая верхняя граница: до конца указанной даты
        q = q.filter(AIImportLog.created_at < date_to + timedelta(days=1))

    search = (request.args.get('search') or '').strip()
    if search:
        like = f'%{search}%'
        q = q.filter(or_(
            AIImportLog.source_url.ilike(like),
            AIImportLog.product_name.ilike(like),
            AIImportLog.user_email.ilike(like),
        ))

    total = q.count()

    page = max(1, request.args.get('page', type=int, default=1))
    per_page = min(200, max(1, request.args.get('per_page', type=int, default=25)))

    rows = (
        q.order_by(desc(AIImportLog.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return jsonify({
        'items': [r.to_dict() for r in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
    })


# ────────────────────────────────────────────────────────────────────────
# Admin GET API: чат
# ────────────────────────────────────────────────────────────────────────

@ai_logs_bp.route('/admin/ai-logs/chats', methods=['GET'])
def list_chat_sessions():
    _, err = _admin_required()
    if err:
        return err

    q = AIChatSession.query

    user_role = request.args.get('user_role')
    if user_role and user_role in _VALID_USER_ROLES:
        q = q.filter(AIChatSession.user_role == user_role)

    user_id = request.args.get('user_id', type=int)
    if user_id:
        q = q.filter(AIChatSession.user_id == user_id)

    date_from = _parse_date(request.args.get('date_from'))
    if date_from:
        q = q.filter(AIChatSession.started_at >= date_from)
    date_to = _parse_date(request.args.get('date_to'))
    if date_to:
        q = q.filter(AIChatSession.started_at < date_to + timedelta(days=1))

    search = (request.args.get('search') or '').strip()
    if search:
        like = f'%{search}%'
        # Поиск по тексту: ищем в email/имени или внутри сообщений сессии.
        # JOIN на messages с DISTINCT, чтобы сессия не дублировалась если
        # совпало несколько сообщений.
        q = (q.outerjoin(AIChatMessage, AIChatMessage.session_id == AIChatSession.id)
             .filter(or_(
                 AIChatSession.user_email.ilike(like),
                 AIChatSession.user_name.ilike(like),
                 AIChatMessage.content.ilike(like),
             ))
             .distinct())

    total = q.count()

    page = max(1, request.args.get('page', type=int, default=1))
    per_page = min(200, max(1, request.args.get('per_page', type=int, default=25)))

    rows = (
        q.order_by(desc(AIChatSession.last_message_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return jsonify({
        'items': [r.to_dict() for r in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@ai_logs_bp.route('/admin/ai-logs/chats/<int:session_id>', methods=['GET'])
def get_chat_session(session_id):
    _, err = _admin_required()
    if err:
        return err

    session = AIChatSession.query.get_or_404(session_id)
    return jsonify(session.to_dict(include_messages=True))


@ai_logs_bp.route('/admin/ai-logs/system-users', methods=['GET'])
def list_logged_system_users():
    """
    Список системных пользователей для UI-фильтра «конкретный юзер».
    Возвращает ВСЕХ актуальных системников из system_users (чтобы можно
    было выбрать любого, даже у кого ещё 0 логов) ПЛЮС merge с
    денормализованными user_id из логов — на случай если юзер был
    удалён, но логи остались.
    """
    _, err = _admin_required()
    if err:
        return err

    from models.systemuser import SystemUser

    by_id: dict[int, dict] = {}

    # 1) Все актуальные системники (включая владельца — он тоже логирует
    #    свои действия, и должен быть выбираем в фильтре)
    for su in SystemUser.query.all():
        by_id[su.id] = {
            'id': su.id,
            'email': su.email,
            'full_name': su.full_name or None,
        }

    # 2) Денормализованные user_id из логов — чтобы юзеры, удалённые
    #    после записи логов, всё равно отображались (FK у нас SET NULL,
    #    но в реальности user_id остаётся в исторических записях если
    #    удаление прошло без cascade — тут страхуемся)
    import_users = db.session.query(
        AIImportLog.user_id, AIImportLog.user_email
    ).filter(
        AIImportLog.user_id.isnot(None),
        AIImportLog.user_role.in_(('admin', 'system')),
    ).distinct().all()

    chat_users = db.session.query(
        AIChatSession.user_id, AIChatSession.user_email, AIChatSession.user_name
    ).filter(
        AIChatSession.user_id.isnot(None),
        AIChatSession.user_role.in_(('admin', 'system')),
    ).distinct().all()

    for uid, email in import_users:
        if uid not in by_id:
            by_id[uid] = {'id': uid, 'email': email, 'full_name': None}
    for uid, email, name in chat_users:
        if uid not in by_id:
            by_id[uid] = {'id': uid, 'email': email, 'full_name': name}

    return jsonify(sorted(by_id.values(), key=lambda u: (u['email'] or '').lower()))
