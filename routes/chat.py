"""
Единый чат-мессенджер CRM.

Комнаты:
- general — общая (одна singleton, все system_users автоматически в ней)
- direct  — личка 1-на-1
- group   — произвольная группа (name обязателен)
- deal    — привязана к сделке (related_deal_id)
- task    — привязана к задаче (related_task_id)

Реалтайм-доставка сообщений — SSE-стрим `/api/admin/chat/stream`.
Один стрим на пользователя, поллит `chat_message` с id > last_seen_id
в комнатах где `chat_member.user_id = me` каждую секунду.
(Redis pubsub — v2, если объёмы вырастут.)

Endpoints:
  GET    /admin/chat/rooms                             мои комнаты + unread + last-message
  POST   /admin/chat/rooms                             создать group
  POST   /admin/chat/rooms/direct                      открыть/создать 1-на-1 с user_id
  GET    /admin/chat/rooms/<id>                        детали + members
  POST   /admin/chat/rooms/<id>/members                add member (group)
  DELETE /admin/chat/rooms/<id>/members/<uid>          remove member (group)

  GET    /admin/chat/rooms/<id>/messages               история (?before=N&limit=50)
  POST   /admin/chat/rooms/<id>/messages               новое сообщение
  POST   /admin/chat/rooms/<id>/read                   mark all read up to now

  PUT    /admin/chat/messages/<id>                     edit text (5 мин)
  DELETE /admin/chat/messages/<id>                     soft delete
  POST   /admin/chat/messages/<id>/reactions           toggle emoji

  GET    /admin/chat/stream                            SSE — все комнаты юзера

Правила видимости:
- Юзер видит комнату только если он `chat_member` этой комнаты.
- Общий (kind='general') должен покрывать всех system_users — membership
  заводится миграцией + при создании нового пользователя (для этого
  крючок — не в этой сессии).
- Для комнат сделок/задач membership заведётся автоматически при
  создании сделки/задачи (крючок — не в этой сессии, отдельно).

Все проверки идут по chat_member — если юзера нет в мембершипе, он
получает 404 (не 403 — не раскрываем существование комнаты).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import or_, and_, func

from extensions import db
from models.chat import (
    ChatRoom, ChatMember, ChatMessage, ChatReaction, ChatAttachment,
    CHAT_ROOM_KINDS,
)
from models.systemuser import SystemUser


chat_bp = Blueprint('chat', __name__)


EDIT_WINDOW_MINUTES = 5


# ============================================================================
# Auth
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


def _require_membership(room_id: int, user_id: int) -> ChatMember | None:
    return ChatMember.query.filter_by(room_id=room_id, user_id=user_id).first()


# ============================================================================
# Serialization
# ============================================================================

def _room_summary(room: ChatRoom, me_id: int) -> dict:
    """Компактное представление комнаты для списка."""
    last_msg = (
        ChatMessage.query.filter_by(room_id=room.id, deleted_at=None)
        .order_by(ChatMessage.created_at.desc()).first()
    )
    my_member = _require_membership(room.id, me_id)

    unread = 0
    if my_member:
        q = ChatMessage.query.filter(
            ChatMessage.room_id == room.id,
            ChatMessage.deleted_at.is_(None),
            ChatMessage.author_id != me_id,  # свои не в unread
        )
        if my_member.last_read_at:
            q = q.filter(ChatMessage.created_at > my_member.last_read_at)
        unread = q.count()

    return {
        'id': room.id,
        'kind': room.kind,
        'name': room.name,
        'related_deal_id': room.related_deal_id,
        'related_task_id': room.related_task_id,
        'created_at': room.created_at.isoformat() if room.created_at else None,
        'updated_at': room.updated_at.isoformat() if room.updated_at else None,
        'last_message': _message_dict(last_msg) if last_msg else None,
        'unread': unread,
    }


def _message_dict(m: ChatMessage) -> dict:
    reactions = ChatReaction.query.filter_by(message_id=m.id).all()
    # Группируем реакции по emoji.
    grouped: dict[str, list[int]] = {}
    for r in reactions:
        grouped.setdefault(r.emoji, []).append(r.user_id)

    attachments = ChatAttachment.query.filter_by(message_id=m.id).all()

    return {
        'id': m.id,
        'room_id': m.room_id,
        'author_id': m.author_id,
        'text': m.text if not m.deleted_at else None,
        'reply_to_id': m.reply_to_id,
        'created_at': m.created_at.isoformat() if m.created_at else None,
        'edited_at': m.edited_at.isoformat() if m.edited_at else None,
        'deleted_at': m.deleted_at.isoformat() if m.deleted_at else None,
        'reactions': [{'emoji': e, 'user_ids': uids} for e, uids in grouped.items()],
        'attachments': [
            {'id': a.id, 'file_url': a.file_url, 'file_name': a.file_name,
             'file_size': a.file_size, 'mime_type': a.mime_type}
            for a in attachments
        ],
    }


# ============================================================================
# Rooms
# ============================================================================

@chat_bp.route('/admin/chat/rooms', methods=['GET'])
@jwt_required()
def list_rooms():
    """
    Все комнаты юзера + last-message + unread. Сортировка — по времени
    последнего сообщения (или created_at если сообщений нет).
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()
    if not uid:
        return jsonify({'error': 'Не авторизован'}), 401

    room_ids = [
        cm.room_id for cm in ChatMember.query.filter_by(user_id=uid).all()
    ]
    if not room_ids:
        return jsonify({'success': True, 'rooms': []}), 200

    rooms = ChatRoom.query.filter(ChatRoom.id.in_(room_ids)).all()
    summaries = [_room_summary(r, uid) for r in rooms]
    summaries.sort(
        key=lambda s: (s['last_message']['created_at'] if s['last_message']
                       else s['created_at']) or '',
        reverse=True,
    )
    return jsonify({'success': True, 'rooms': summaries}), 200


@chat_bp.route('/admin/chat/rooms', methods=['POST'])
@jwt_required()
def create_group_room():
    """
    Создать group-комнату.
    Body: {"name": "...", "user_ids": [1, 2, 3]}
    Создатель автоматически становится участником.
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()
    if not uid:
        return jsonify({'error': 'Не авторизован'}), 401

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name обязателен'}), 400
    user_ids = data.get('user_ids') or []
    if not isinstance(user_ids, list):
        return jsonify({'error': 'user_ids должен быть массивом'}), 400

    room = ChatRoom(kind='group', name=name)
    db.session.add(room)
    db.session.flush()

    seen: set[int] = set()
    for u in [uid, *user_ids]:
        try:
            u = int(u)
        except (TypeError, ValueError):
            continue
        if u in seen:
            continue
        if not SystemUser.query.get(u):
            continue
        db.session.add(ChatMember(room_id=room.id, user_id=u))
        seen.add(u)

    db.session.commit()
    return jsonify({'success': True, 'room': _room_summary(room, uid)}), 201


@chat_bp.route('/admin/chat/rooms/direct', methods=['POST'])
@jwt_required()
def open_direct_room():
    """
    Открыть или создать личную переписку с конкретным юзером.
    Body: {"user_id": N}
    Возвращает room. Идемпотентно: если direct-комната между этими
    двумя юзерами уже есть — вернём её.
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()
    if not uid:
        return jsonify({'error': 'Не авторизован'}), 401

    data = request.get_json() or {}
    try:
        target_uid = int(data['user_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'user_id обязателен'}), 400
    if target_uid == uid:
        return jsonify({'error': 'Нельзя открыть личку с собой'}), 400
    if not SystemUser.query.get(target_uid):
        return jsonify({'error': 'Пользователь не найден'}), 404

    # Ищем direct-комнату где оба юзера — участники.
    # Сначала комнаты юзера-me, из них берём id-шники → комнаты с target тоже.
    my_rooms = [
        cm.room_id for cm in ChatMember.query.filter_by(user_id=uid).all()
    ]
    direct_room_id = db.session.query(ChatRoom.id).filter(
        ChatRoom.id.in_(my_rooms),
        ChatRoom.kind == 'direct',
    ).join(ChatMember, ChatMember.room_id == ChatRoom.id).filter(
        ChatMember.user_id == target_uid,
    ).first()

    if direct_room_id:
        room = db.session.get(ChatRoom, direct_room_id[0])
        return jsonify({'success': True, 'room': _room_summary(room, uid)}), 200

    room = ChatRoom(kind='direct')
    db.session.add(room)
    db.session.flush()
    db.session.add(ChatMember(room_id=room.id, user_id=uid))
    db.session.add(ChatMember(room_id=room.id, user_id=target_uid))
    db.session.commit()
    return jsonify({'success': True, 'room': _room_summary(room, uid)}), 201


@chat_bp.route('/admin/chat/rooms/<int:rid>', methods=['GET'])
@jwt_required()
def get_room(rid):
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404

    members = ChatMember.query.filter_by(room_id=rid).all()
    d = _room_summary(room, uid)
    d['members'] = [
        {'id': m.id, 'user_id': m.user_id,
         'joined_at': m.joined_at.isoformat() if m.joined_at else None,
         'last_read_at': m.last_read_at.isoformat() if m.last_read_at else None}
        for m in members
    ]
    return jsonify({'success': True, 'room': d}), 200


@chat_bp.route('/admin/chat/rooms/<int:rid>/members', methods=['POST'])
@jwt_required()
def add_room_member(rid):
    """Только для group. Body: {"user_id": N}"""
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404
    if room.kind != 'group':
        return jsonify({'error': 'Добавлять участников можно только в группу'}), 400

    data = request.get_json() or {}
    try:
        target_uid = int(data['user_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'user_id обязателен'}), 400
    if not SystemUser.query.get(target_uid):
        return jsonify({'error': 'Пользователь не найден'}), 404
    if ChatMember.query.filter_by(room_id=rid, user_id=target_uid).first():
        return jsonify({'success': True}), 200  # уже участник

    db.session.add(ChatMember(room_id=rid, user_id=target_uid))
    db.session.commit()
    return jsonify({'success': True}), 201


@chat_bp.route('/admin/chat/rooms/<int:rid>/members/<int:mid>', methods=['DELETE'])
@jwt_required()
def remove_room_member(rid, mid):
    err = _check_admin_or_system()
    if err:
        return err
    role, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404
    if room.kind != 'group':
        return jsonify({'error': 'Удалять участников можно только из группы'}), 400
    # Себя можно всегда, других — admin.
    if mid != uid and role != 'admin':
        return jsonify({'error': 'Нет прав удалять других участников'}), 403

    m = ChatMember.query.filter_by(room_id=rid, user_id=mid).first()
    if not m:
        return jsonify({'error': 'Участник не найден'}), 404

    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Messages
# ============================================================================

@chat_bp.route('/admin/chat/rooms/<int:rid>/messages', methods=['GET'])
@jwt_required()
def list_messages(rid):
    """
    История сообщений с пагинацией вверх (before=<message_id>).
    limit по умолчанию 50, max 200.
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404

    limit = min(request.args.get('limit', 50, type=int), 200)
    before = request.args.get('before', type=int)

    q = ChatMessage.query.filter(ChatMessage.room_id == rid)
    if before:
        q = q.filter(ChatMessage.id < before)
    messages = q.order_by(ChatMessage.created_at.desc()).limit(limit).all()
    # Возвращаем в chronological order (старые первыми) — так фронту удобнее.
    messages.reverse()
    return jsonify({
        'success': True,
        'messages': [_message_dict(m) for m in messages],
        'has_more': len(messages) == limit,
    }), 200


@chat_bp.route('/admin/chat/rooms/<int:rid>/messages', methods=['POST'])
@jwt_required()
def send_message(rid):
    """
    Новое сообщение. Body: {"text": "...", "reply_to_id": N (опц.)}
    Файлы прикрепляются отдельно — Этап 5.5 (не в этой сессии, там
    upload через upload_admin_bp).
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'text обязателен'}), 400
    if len(text) > 10_000:
        return jsonify({'error': 'text слишком длинный (макс 10000)'}), 400

    reply_to_id = data.get('reply_to_id')
    if reply_to_id is not None:
        try:
            reply_to_id = int(reply_to_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'reply_to_id должен быть числом'}), 400
        # Проверяем что цитируемое сообщение из той же комнаты.
        target = db.session.get(ChatMessage, reply_to_id)
        if not target or target.room_id != rid:
            return jsonify({'error': 'reply_to_id не из этой комнаты'}), 400

    msg = ChatMessage(
        room_id=rid, author_id=uid,
        text=text, reply_to_id=reply_to_id,
    )
    db.session.add(msg)
    # Bump `updated_at` комнаты чтобы фронт-сортировка по last-message
    # работала стабильно даже когда SSE не подхватил.
    room.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'message': _message_dict(msg)}), 201


@chat_bp.route('/admin/chat/messages/<int:mid>', methods=['PUT'])
@jwt_required()
def edit_message(mid):
    """Редактирование текста своего сообщения в течение 5 мин."""
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    msg = db.session.get(ChatMessage, mid)
    if not msg:
        return jsonify({'error': 'Сообщение не найдено'}), 404
    if msg.deleted_at:
        return jsonify({'error': 'Сообщение удалено'}), 400
    if msg.author_id != uid:
        return jsonify({'error': 'Можно редактировать только свои'}), 403
    if not _require_membership(msg.room_id, uid):
        return jsonify({'error': 'Не участник комнаты'}), 403

    if (datetime.utcnow() - (msg.created_at or datetime.utcnow())) > timedelta(minutes=EDIT_WINDOW_MINUTES):
        return jsonify({'error': f'Редактировать можно только в первые {EDIT_WINDOW_MINUTES} минут'}), 400

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'text обязателен'}), 400
    if len(text) > 10_000:
        return jsonify({'error': 'text слишком длинный (макс 10000)'}), 400

    msg.text = text
    msg.edited_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'message': _message_dict(msg)}), 200


@chat_bp.route('/admin/chat/messages/<int:mid>', methods=['DELETE'])
@jwt_required()
def delete_message(mid):
    """
    Soft delete — сообщение остаётся для целостности reply-ссылок, но
    text скрывается («Сообщение удалено»). Своё — всегда, чужое — только
    admin.
    """
    err = _check_admin_or_system()
    if err:
        return err
    role, uid = _current_role_and_id()

    msg = db.session.get(ChatMessage, mid)
    if not msg:
        return jsonify({'error': 'Сообщение не найдено'}), 404
    if not _require_membership(msg.room_id, uid):
        return jsonify({'error': 'Не участник комнаты'}), 403
    if msg.author_id != uid and role != 'admin':
        return jsonify({'error': 'Можно удалить только своё сообщение'}), 403

    msg.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Reactions
# ============================================================================

@chat_bp.route('/admin/chat/messages/<int:mid>/reactions', methods=['POST'])
@jwt_required()
def toggle_reaction(mid):
    """
    Тумблер — если такой (message, user, emoji) уже есть, снимаем;
    иначе ставим.
    Body: {"emoji": "👍"}
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    msg = db.session.get(ChatMessage, mid)
    if not msg:
        return jsonify({'error': 'Сообщение не найдено'}), 404
    if not _require_membership(msg.room_id, uid):
        return jsonify({'error': 'Не участник комнаты'}), 403

    data = request.get_json() or {}
    emoji = (data.get('emoji') or '').strip()
    if not emoji or len(emoji) > 16:
        return jsonify({'error': 'emoji обязательна, макс 16 символов'}), 400

    existing = ChatReaction.query.filter_by(
        message_id=mid, user_id=uid, emoji=emoji,
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'success': True, 'action': 'removed'}), 200

    db.session.add(ChatReaction(message_id=mid, user_id=uid, emoji=emoji))
    db.session.commit()
    return jsonify({'success': True, 'action': 'added'}), 201


# ============================================================================
# Read markers
# ============================================================================

@chat_bp.route('/admin/chat/rooms/<int:rid>/read', methods=['POST'])
@jwt_required()
def mark_read(rid):
    """Ставит last_read_at = now — обнуляет unread для комнаты."""
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    m = _require_membership(rid, uid)
    if not m:
        return jsonify({'error': 'Комната не найдена'}), 404

    m.last_read_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# SSE stream — все комнаты юзера в одном потоке
# ============================================================================

@chat_bp.route('/admin/chat/stream', methods=['GET'])
def chat_stream():
    """
    SSE-стрим новых сообщений и реакций во всех комнатах юзера.
    JWT — через ?token= query (EventSource не умеет кастомные заголовки).

    Поллит `chat_message.id > last_message_id` в моих комнатах каждую
    секунду. Ping каждые 25 сек чтобы прокси не рвали keep-alive.

    Events:
      event: message   — новое сообщение (или edited/deleted)
      event: reaction  — изменена реакция
      : ping <ts>      — heartbeat

    Клиент запоминает `last_message_id` и переподключается — не
    гарантируем at-least-once, но простая переустановка после разрыва
    сети дотягивает новые сообщения.
    """
    token = request.args.get('token')
    if token:
        request.environ['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({'error': 'unauthorized'}), 401

    role, uid = _current_role_and_id()
    if role not in ('admin', 'system') or not uid:
        return jsonify({'error': 'forbidden'}), 403

    app = current_app._get_current_object()

    def event_gen():
        with app.app_context():
            last_message_id = request.args.get('since', type=int) or 0
            last_reaction_id = request.args.get('since_reaction', type=int) or 0
            last_ping = time.time()

            while True:
                db.session.expire_all()

                # Комнаты юзера обновляем каждую итерацию — юзера могли
                # добавить/удалить из группы, не хочу закешировать.
                my_rooms = [
                    cm.room_id for cm in
                    ChatMember.query.filter_by(user_id=uid).all()
                ]
                if not my_rooms:
                    time.sleep(2)
                    continue

                # Новые сообщения.
                new_msgs = (
                    ChatMessage.query.filter(
                        ChatMessage.room_id.in_(my_rooms),
                        ChatMessage.id > last_message_id,
                    )
                    .order_by(ChatMessage.id.asc())
                    .limit(50)
                    .all()
                )
                for m in new_msgs:
                    payload = json.dumps(_message_dict(m), ensure_ascii=False, default=str)
                    yield f'event: message\ndata: {payload}\n\n'
                    last_message_id = m.id
                    last_ping = time.time()

                # Новые реакции.
                new_reactions = (
                    ChatReaction.query.join(
                        ChatMessage, ChatMessage.id == ChatReaction.message_id
                    ).filter(
                        ChatMessage.room_id.in_(my_rooms),
                        ChatReaction.id > last_reaction_id,
                    )
                    .order_by(ChatReaction.id.asc())
                    .limit(50)
                    .all()
                )
                for r in new_reactions:
                    payload = json.dumps({
                        'message_id': r.message_id,
                        'user_id': r.user_id,
                        'emoji': r.emoji,
                        'action': 'added',
                    }, ensure_ascii=False)
                    yield f'event: reaction\ndata: {payload}\n\n'
                    last_reaction_id = r.id
                    last_ping = time.time()

                if time.time() - last_ping > 25:
                    yield f': ping {int(time.time())}\n\n'
                    last_ping = time.time()

                time.sleep(1)

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    }
    return Response(stream_with_context(event_gen()), headers=headers)
