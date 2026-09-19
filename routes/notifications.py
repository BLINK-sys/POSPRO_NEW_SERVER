"""
Endpoints для системы уведомлений.

Bell + панель:
  GET  /admin/notifications          список моих (пагинация, ?unread=1)
  POST /admin/notifications/read     batch mark_read (ids: [...])
  POST /admin/notifications/read-all mark all read

Счётчики для красных точек на pill'ах в шапке админки:
  GET  /admin/notifications/counts   {total_unread, by_section: {deals, tasks, chat}}

Web Push подписки:
  GET  /admin/notifications/vapid-public    публичный ключ для PushManager.subscribe()
  POST /admin/notifications/push-subscribe  сохранить subscription
  POST /admin/notifications/push-unsubscribe   удалить subscription (по endpoint)
  POST /admin/notifications/push-test       тестовый push самому себе (диагностика)

Presence:
  POST /admin/notifications/heartbeat  обновить last_heartbeat_at + current_section
  GET  /admin/notifications/online     карта {user_id: {online, section}}
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models.notification import (
    Notification, WebPushSubscription, UserPresence, NOTIFICATION_SECTIONS,
)
from models.systemuser import SystemUser
from services.notifications import (
    VAPID_PUBLIC_KEY, is_web_push_configured, send_web_push,
)


notifications_bp = Blueprint('notifications', __name__)


# ============================================================================
# Auth
# ============================================================================

def _check():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _uid() -> int | None:
    try:
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        return None


# ============================================================================
# Bell + панель
# ============================================================================

@notifications_bp.route('/admin/notifications', methods=['GET'])
@jwt_required()
def list_notifications():
    """
    Мои уведомления. По умолчанию — все, сортированные по created_at DESC.
    ?unread=1 — только непрочитанные.
    ?section=deals — фильтр по секции.
    ?limit=50&offset=0 — пагинация.
    """
    err = _check()
    if err:
        return err
    uid = _uid()
    if not uid:
        return jsonify({'error': 'Не авторизован'}), 401

    q = Notification.query.filter_by(user_id=uid)
    if request.args.get('unread') == '1':
        q = q.filter(Notification.read_at.is_(None))
    section = request.args.get('section')
    if section in NOTIFICATION_SECTIONS:
        q = q.filter_by(section=section)

    total = q.count()
    limit = min(request.args.get('limit', 50, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)

    items = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset).all()
    return jsonify({
        'success': True,
        'notifications': [n.to_dict() for n in items],
        'total': total,
        'limit': limit,
        'offset': offset,
    }), 200


@notifications_bp.route('/admin/notifications/read', methods=['POST'])
@jwt_required()
def mark_read_batch():
    """Body: {"ids": [1, 2, 3]} — mark_read этих ID (только свои)."""
    err = _check()
    if err:
        return err
    uid = _uid()
    data = request.get_json() or {}
    ids = data.get('ids') or []
    if not isinstance(ids, list):
        return jsonify({'error': 'ids должен быть массивом'}), 400

    ids = [i for i in ids if isinstance(i, int)]
    if not ids:
        return jsonify({'success': True, 'updated': 0}), 200

    now = datetime.utcnow()
    updated = Notification.query.filter(
        Notification.user_id == uid,
        Notification.id.in_(ids),
        Notification.read_at.is_(None),
    ).update({'read_at': now}, synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True, 'updated': updated}), 200


@notifications_bp.route('/admin/notifications/read-all', methods=['POST'])
@jwt_required()
def mark_all_read():
    err = _check()
    if err:
        return err
    uid = _uid()

    now = datetime.utcnow()
    updated = Notification.query.filter(
        Notification.user_id == uid,
        Notification.read_at.is_(None),
    ).update({'read_at': now}, synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True, 'updated': updated}), 200


# ============================================================================
# Counts (красные точки)
# ============================================================================

@notifications_bp.route('/admin/notifications/counts', methods=['GET'])
@jwt_required()
def counts():
    """
    Счётчики непрочитанных для UI-точек. Секции — deals/tasks/chat.
    """
    err = _check()
    if err:
        return err
    uid = _uid()

    rows = db.session.query(
        Notification.section, db.func.count(Notification.id)
    ).filter(
        Notification.user_id == uid,
        Notification.read_at.is_(None),
    ).group_by(Notification.section).all()

    by_section = {s: 0 for s in NOTIFICATION_SECTIONS}
    total = 0
    for section, cnt in rows:
        if section in by_section:
            by_section[section] = int(cnt)
        total += int(cnt)

    return jsonify({
        'success': True,
        'total_unread': total,
        'by_section': by_section,
    }), 200


# ============================================================================
# Web Push
# ============================================================================

@notifications_bp.route('/admin/notifications/vapid-public', methods=['GET'])
@jwt_required()
def get_vapid_public():
    err = _check()
    if err:
        return err
    if not VAPID_PUBLIC_KEY:
        return jsonify({'success': True, 'public_key': None, 'configured': False}), 200
    return jsonify({
        'success': True,
        'public_key': VAPID_PUBLIC_KEY,
        'configured': True,
    }), 200


@notifications_bp.route('/admin/notifications/push-subscribe', methods=['POST'])
@jwt_required()
def push_subscribe():
    """
    Body: {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}
    Приходит от `PushManager.subscribe()` на клиенте.
    Один endpoint = одна подписка (uq_web_push_endpoint).
    """
    err = _check()
    if err:
        return err
    uid = _uid()

    data = request.get_json() or {}
    endpoint = (data.get('endpoint') or '').strip()
    keys = data.get('keys') or {}
    if not endpoint or not isinstance(keys, dict):
        return jsonify({'error': 'endpoint и keys обязательны'}), 400
    if 'p256dh' not in keys or 'auth' not in keys:
        return jsonify({'error': 'keys должен содержать p256dh и auth'}), 400

    ua = (request.headers.get('User-Agent') or '')[:500]

    existing = WebPushSubscription.query.filter_by(endpoint=endpoint).first()
    if existing:
        existing.user_id = uid  # переприсваиваем на всякий если тот же браузер сменил юзера
        existing.keys = keys
        existing.user_agent = ua
    else:
        existing = WebPushSubscription(
            user_id=uid, endpoint=endpoint, keys=keys, user_agent=ua,
        )
        db.session.add(existing)
    db.session.commit()
    return jsonify({'success': True, 'subscription_id': existing.id}), 201


@notifications_bp.route('/admin/notifications/push-unsubscribe', methods=['POST'])
@jwt_required()
def push_unsubscribe():
    """Body: {"endpoint": "..."} — удаляет подписку. Только свою."""
    err = _check()
    if err:
        return err
    uid = _uid()

    data = request.get_json() or {}
    endpoint = (data.get('endpoint') or '').strip()
    if not endpoint:
        return jsonify({'error': 'endpoint обязателен'}), 400

    sub = WebPushSubscription.query.filter_by(endpoint=endpoint, user_id=uid).first()
    if not sub:
        return jsonify({'success': True}), 200  # уже нет

    db.session.delete(sub)
    db.session.commit()
    return jsonify({'success': True}), 200


@notifications_bp.route('/admin/notifications/push-test', methods=['POST'])
@jwt_required()
def push_test():
    """
    Тестовый push самому себе — для проверки VAPID-ключей и подписок.
    Body: {"title": "Тест", "body": "Работает"} (оба опц.).
    """
    err = _check()
    if err:
        return err
    uid = _uid()

    if not is_web_push_configured():
        return jsonify({
            'success': False,
            'error': 'Web Push не сконфигурирован. Задай VAPID_PUBLIC_KEY и VAPID_PRIVATE_KEY в env.',
        }), 400

    data = request.get_json() or {}
    title = (data.get('title') or 'Тест PosPro').strip()
    body = (data.get('body') or 'Web Push работает 🎉').strip()

    subs = WebPushSubscription.query.filter_by(user_id=uid).all()
    if not subs:
        return jsonify({
            'success': False,
            'error': 'Нет активных подписок. Разреши уведомления в браузере и подпишись.',
        }), 400

    sent = 0
    failed = 0
    for sub in subs:
        ok = send_web_push(sub, title, body, url='/admin')
        if ok:
            sub.last_used_at = datetime.utcnow()
            sent += 1
        else:
            failed += 1
    db.session.commit()
    return jsonify({'success': True, 'sent': sent, 'failed': failed, 'total_subs': len(subs)}), 200


# ============================================================================
# Presence
# ============================================================================

@notifications_bp.route('/admin/notifications/heartbeat', methods=['POST'])
@jwt_required()
def heartbeat():
    """
    Обновляет last_heartbeat_at и current_section юзера. Фронт шлёт раз
    в 30 сек с активной admin-вкладки.
    Body: {"section": "deals" | ...} — опционально.
    """
    err = _check()
    if err:
        return err
    uid = _uid()

    data = request.get_json(silent=True) or {}
    section = data.get('section')
    if section and not isinstance(section, str):
        section = None
    if section:
        section = section[:32]

    presence = db.session.get(UserPresence, uid)
    now = datetime.utcnow()
    if presence:
        presence.last_heartbeat_at = now
        if section:
            presence.current_section = section
    else:
        presence = UserPresence(
            user_id=uid, last_heartbeat_at=now,
            current_section=section,
        )
        db.session.add(presence)

    # Плюс дублируем в system_users.last_seen (используется в
    # /admin/user-activity).
    su = db.session.get(SystemUser, uid)
    if su:
        su.last_seen = now

    db.session.commit()
    return jsonify({'success': True}), 200


@notifications_bp.route('/admin/notifications/online', methods=['GET'])
@jwt_required()
def online_users():
    """
    Карта {user_id: {online: bool, section: str|null}} по всем system_users.
    Используется чат-UI для 🟢 индикатора.
    """
    err = _check()
    if err:
        return err

    presences = {p.user_id: p for p in UserPresence.query.all()}
    users = SystemUser.query.all()

    out = {}
    for u in users:
        p = presences.get(u.id)
        out[u.id] = {
            'online': bool(p and p.is_online()),
            'section': p.current_section if p else None,
        }
    return jsonify({'success': True, 'presence': out}), 200
