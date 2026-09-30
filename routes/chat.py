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

import os
import re
import unicodedata

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


def _room_push_url(room: ChatRoom) -> str:
    """URL для клика по push-уведомлению → SW откроет эту вкладку."""
    if room.kind == 'deal' and room.related_deal_id:
        return f'/admin/deals/{room.related_deal_id}'
    if room.kind == 'task' and room.related_task_id:
        return f'/admin/tasks/{room.related_task_id}'
    return '/admin/chat'


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
    # `after=<message_id>` — для мягкого polling'а из карточки сделки.
    # Возвращаем только сообщения с id > after, в chronological order.
    after = request.args.get('after', type=int)

    q = ChatMessage.query.filter(ChatMessage.room_id == rid)
    if before:
        q = q.filter(ChatMessage.id < before)
    if after:
        q = q.filter(ChatMessage.id > after)

    if after:
        # asc сразу — polling ожидает старые → новые.
        messages = q.order_by(ChatMessage.id.asc()).limit(limit).all()
    else:
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

    # Уведомления всем участникам кроме автора. best-effort. @упоминания —
    # v2 (пока просто chat_new_message для всех). Web Push шлём всегда —
    # Service Worker сам решает показывать или нет: если открытая вкладка
    # /admin/chat уже есть, SW тихо гасит уведомление.
    try:
        from services.notifications import notify
        from models.systemuser import SystemUser
        preview = (text[:80] + '…') if len(text) > 80 else text
        author = db.session.get(SystemUser, uid)
        author_name = (author.full_name if author else None) or 'Кто-то'
        push_url = _room_push_url(room)
        other_members = ChatMember.query.filter(
            ChatMember.room_id == rid,
            ChatMember.user_id != uid,
        ).all()
        for m in other_members:
            notify(
                user_id=m.user_id, kind='chat_new_message',
                section='chat', entity_type='chat_room', entity_id=rid,
                payload={'author_id': uid, 'preview': preview,
                         'room_id': rid, 'room_kind': room.kind},
                push_title=author_name,
                push_body=preview,
                push_url=push_url,
            )
        db.session.commit()
    except Exception as e:
        print(f'⚠️ notify (chat) failed: {e}', flush=True)

    return jsonify({'success': True, 'message': _message_dict(msg)}), 201


@chat_bp.route('/admin/chat/rooms/<int:rid>/messages/upload', methods=['POST'])
@jwt_required()
def upload_message(rid):
    """
    Отправка сообщения со вложением. Multipart form-data:
      file       — файл (можно несколько с одинаковым именем поля)
      text       — опциональный текст сообщения
      reply_to_id — опционально

    Файл кладётся на диск под `crm_attachments/<entity_type>/<entity_id>/`
    если комната привязана к сделке/задаче, иначе `crm_chat/<rid>/`.
    Для deal/task-комнат параллельно создаётся `EntityAttachment` —
    чтобы файл, прикреплённый в чате, автоматически появлялся в разделе
    «Документы» сущности.
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404

    files = request.files.getlist('file')
    files = [f for f in files if f and f.filename]
    text = (request.form.get('text') or '').strip()
    if not files and not text:
        return jsonify({'error': 'Нужен файл или текст'}), 400
    if len(text) > 10_000:
        return jsonify({'error': 'text слишком длинный (макс 10000)'}), 400

    reply_to_id_raw = request.form.get('reply_to_id')
    reply_to_id = None
    if reply_to_id_raw:
        try:
            reply_to_id = int(reply_to_id_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'reply_to_id должен быть числом'}), 400
        target = db.session.get(ChatMessage, reply_to_id)
        if not target or target.room_id != rid:
            return jsonify({'error': 'reply_to_id не из этой комнаты'}), 400

    allowed = current_app.config['ALLOWED_EXTENSIONS']

    def _sanitize(name: str) -> str:
        name = unicodedata.normalize('NFKD', name)
        name = re.sub(r'[/\\?%*:|"<>]', '_', name)
        return name.strip() or 'file'

    def _is_allowed(fn: str) -> bool:
        return '.' in fn and fn.rsplit('.', 1)[1].lower() in allowed

    # Определяем entity-контекст для параллельной записи в
    # EntityAttachment (для «Документов» сделки/задачи).
    entity_type: str | None = None
    entity_id: int | None = None
    if room.kind == 'deal' and room.related_deal_id:
        entity_type, entity_id = 'deal', room.related_deal_id
    elif room.kind == 'task' and room.related_task_id:
        entity_type, entity_id = 'task', room.related_task_id

    root = current_app.config['UPLOAD_FOLDER']
    if entity_type and entity_id:
        subfolder = os.path.join('crm_attachments', entity_type, str(entity_id))
        url_prefix = f'/uploads/crm_attachments/{entity_type}/{entity_id}'
    else:
        subfolder = os.path.join('crm_chat', str(rid))
        url_prefix = f'/uploads/crm_chat/{rid}'
    folder = os.path.join(root, subfolder)
    os.makedirs(folder, exist_ok=True)

    # Валидация всех файлов до сохранения — так частично не сохранится.
    for f in files:
        if not _is_allowed(f.filename):
            return jsonify({
                'error': f'Тип файла не разрешён: {f.filename}',
                'allowed': sorted(allowed),
            }), 400

    # Создаём сообщение (даже если text пустой — тогда просто вложения).
    msg = ChatMessage(
        room_id=rid, author_id=uid,
        text=text or None, reply_to_id=reply_to_id,
    )
    db.session.add(msg)
    db.session.flush()

    # Импорт локально чтобы не тянуть при обычной отправке текста.
    from models.entity_attachment import EntityAttachment

    saved_attachments = []
    for f in files:
        original = _sanitize(f.filename)
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
        ext = os.path.splitext(original)[1]
        disk_name = f'{ts}{ext}'
        disk_path = os.path.join(folder, disk_name)
        f.save(disk_path)
        size = os.path.getsize(disk_path)
        file_url = f'{url_prefix}/{disk_name}'

        ca = ChatAttachment(
            message_id=msg.id, file_url=file_url, file_name=original,
            file_size=size, mime_type=(f.mimetype or None),
        )
        db.session.add(ca)
        saved_attachments.append(ca)

        # Параллельно — EntityAttachment для «Документов» сделки/задачи.
        if entity_type and entity_id:
            ea = EntityAttachment(
                entity_type=entity_type, entity_id=entity_id,
                file_url=file_url, file_name=original,
                file_size=size, mime_type=(f.mimetype or None),
                title=None, uploaded_by=uid,
            )
            db.session.add(ea)

    room.updated_at = datetime.utcnow()
    db.session.commit()

    # Уведомления как в send_message.
    try:
        from services.notifications import notify
        from models.systemuser import SystemUser
        preview = text[:80] if text else f'📎 {len(files)} файл(ов)'
        author = db.session.get(SystemUser, uid)
        author_name = (author.full_name if author else None) or 'Кто-то'
        push_url = _room_push_url(room)
        for m in ChatMember.query.filter(
            ChatMember.room_id == rid,
            ChatMember.user_id != uid,
        ).all():
            notify(
                user_id=m.user_id, kind='chat_new_message',
                section='chat', entity_type='chat_room', entity_id=rid,
                payload={'author_id': uid, 'preview': preview,
                         'has_attachments': True,
                         'room_id': rid, 'room_kind': room.kind},
                push_title=author_name,
                push_body=preview,
                push_url=push_url,
            )
        db.session.commit()
    except Exception as e:
        print(f'⚠️ notify (chat upload) failed: {e}', flush=True)

    return jsonify({'success': True, 'message': _message_dict(msg)}), 201


@chat_bp.route('/admin/chat/rooms/<int:rid>/read-status', methods=['GET'])
@jwt_required()
def read_status(rid):
    """
    Read-receipts для чата: возвращает `last_read_at` каждого участника
    комнаты. Фронт сам сравнивает с `created_at` сообщения, чтобы
    вычислить кто из членов уже прочитал именно это сообщение —
    отдельной таблицы `chat_message_read` не заводим, обходимся
    `chat_member.last_read_at` (обновляется при open чата / POST /read).
    """
    err = _check_admin_or_system()
    if err:
        return err
    _, uid = _current_role_and_id()

    room = db.session.get(ChatRoom, rid)
    if not room or not _require_membership(rid, uid):
        return jsonify({'error': 'Комната не найдена'}), 404

    members = ChatMember.query.filter_by(room_id=rid).all()
    return jsonify({
        'success': True,
        'members': [
            {
                'user_id': m.user_id,
                'last_read_at': m.last_read_at.isoformat() if m.last_read_at else None,
            }
            for m in members
        ],
    }), 200


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
      event: message       — новое сообщение (или edited/deleted)
      event: reaction      — изменена реакция
      event: read          — участник комнаты обновил last_read_at (для «глаза»)
      event: notification  — новая запись в notification (bell + звук)
      : ping <ts>          — heartbeat

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
            # Notification для этого юзера: стартуем с максимального
            # существующего id — старые не пересылаем (bell-панель их
            # покажет через /admin/notifications).
            from models.notification import Notification as _NModel
            last_notif_row = (
                _NModel.query.filter_by(user_id=uid)
                .order_by(_NModel.id.desc()).first()
            )
            last_notification_id = last_notif_row.id if last_notif_row else 0
            # Ловим только read/edit/delete события ПОСЛЕ подключения —
            # старые клиент забрал первичным snapshot'ом.
            last_read_check = datetime.utcnow()
            last_edit_check = datetime.utcnow()
            last_delete_check = datetime.utcnow()
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

                # Отредактированные и удалённые сообщения. Тем же event: message
                # шлём обновлённый _message_dict — фронт-mergeMessages
                # заменит по id. Клиент видит правку/удаление без F5.
                now_edit = datetime.utcnow()
                edited_msgs = (
                    ChatMessage.query.filter(
                        ChatMessage.room_id.in_(my_rooms),
                        ChatMessage.edited_at.isnot(None),
                        ChatMessage.edited_at > last_edit_check,
                    )
                    .limit(50)
                    .all()
                )
                deleted_msgs = (
                    ChatMessage.query.filter(
                        ChatMessage.room_id.in_(my_rooms),
                        ChatMessage.deleted_at.isnot(None),
                        ChatMessage.deleted_at > last_delete_check,
                    )
                    .limit(50)
                    .all()
                )
                seen_ids = set()
                for m in (list(edited_msgs) + list(deleted_msgs)):
                    if m.id in seen_ids:
                        continue
                    seen_ids.add(m.id)
                    payload = json.dumps(_message_dict(m), ensure_ascii=False, default=str)
                    yield f'event: message\ndata: {payload}\n\n'
                    last_ping = time.time()
                last_edit_check = now_edit
                last_delete_check = now_edit

                # Свежие read-receipts от других участников.
                # Фильтр: чужие read-marks (свои клиент и так знает), в
                # моих комнатах, обновлённые с прошлой итерации. Клиент
                # использует это чтобы обновить «глаз прочитано» без
                # polling'а /read-status.
                now_check = datetime.utcnow()
                new_reads = (
                    ChatMember.query.filter(
                        ChatMember.room_id.in_(my_rooms),
                        ChatMember.user_id != uid,
                        ChatMember.last_read_at.isnot(None),
                        ChatMember.last_read_at > last_read_check,
                    )
                    .limit(100)
                    .all()
                )
                for cm in new_reads:
                    payload = json.dumps({
                        'room_id': cm.room_id,
                        'user_id': cm.user_id,
                        'last_read_at': cm.last_read_at.isoformat() if cm.last_read_at else None,
                    }, ensure_ascii=False)
                    yield f'event: read\ndata: {payload}\n\n'
                    last_ping = time.time()
                last_read_check = now_check

                # Свежие Notification для этого юзера — bell-панель и
                # звук на разные типы (deal_assigned / task_assigned /
                # chat_new_message / …).
                from models.notification import Notification as _N
                new_notifs = (
                    _N.query.filter(
                        _N.user_id == uid,
                        _N.id > last_notification_id,
                    )
                    .order_by(_N.id.asc())
                    .limit(50)
                    .all()
                )
                for n in new_notifs:
                    payload = json.dumps(n.to_dict(), ensure_ascii=False, default=str)
                    yield f'event: notification\ndata: {payload}\n\n'
                    last_notification_id = n.id
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
