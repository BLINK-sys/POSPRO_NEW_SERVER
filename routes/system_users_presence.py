"""
Presence-трекинг системных пользователей.

Поток:
  - Фронт из `pospro_new_ui/app/admin/layout.tsx` каждые 60 сек шлёт
    POST /auth/heartbeat пока вкладка с админкой открыта.
  - Бэк обновляет `system_users.last_seen = now()`.
  - Owner (single user, `system_users.is_owner = TRUE`) видит таблицу
    /admin/user-activity где для каждого системного юзера показано:
    email, full_name, роль (owner / admin / system), is_online (был
    активен в последние ONLINE_THRESHOLD_SECONDS), last_seen.

«Онлайн» = last_seen в пределах последних 120 секунд (запас над
heartbeat'ом 60 сек). Если юзер просто закрыл вкладку — через 2 минуты
автоматически уходит в офлайн.
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from extensions import db
from models.systemuser import SystemUser
from routes.auth import is_owner_user

presence_bp = Blueprint('presence', __name__)

ONLINE_THRESHOLD_SECONDS = 120


@presence_bp.route('/auth/heartbeat', methods=['POST'])
@jwt_required()
def heartbeat():
    """
    Обновить last_seen для текущего системного пользователя. Клиентов
    (роль `client`) тихо игнорируем — их в `system_users` нет.
    """
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'success': True, 'tracked': False}), 200

    try:
        uid = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({'success': False}), 200

    su = SystemUser.query.get(uid)
    if not su:
        return jsonify({'success': False}), 200

    su.last_seen = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'success': True, 'tracked': True}), 200


@presence_bp.route('/api/admin/system-users/presence', methods=['GET'])
@jwt_required()
def list_presence():
    """
    Owner-only: вернуть всех системных пользователей с признаком is_online
    и временем последней активности. Сортировка: онлайн первыми, потом
    по убыванию last_seen.
    """
    try:
        viewer_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({'error': 'Не авторизован'}), 401

    if not is_owner_user(viewer_id):
        return jsonify({'error': 'Доступ запрещён'}), 403

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=ONLINE_THRESHOLD_SECONDS)

    users = SystemUser.query.order_by(SystemUser.full_name).all()
    rows = []
    for u in users:
        last_seen_aware = u.last_seen
        # Постгрес TIMESTAMPTZ → tz-aware datetime, но если БД отдала
        # naive (например после ALTER на старой колонке) — считаем UTC.
        if last_seen_aware and last_seen_aware.tzinfo is None:
            last_seen_aware = last_seen_aware.replace(tzinfo=timezone.utc)
        is_online = bool(last_seen_aware and last_seen_aware >= threshold)
        rows.append({
            'id': u.id,
            'full_name': u.full_name,
            'email': u.email,
            'is_owner': bool(u.is_owner),
            'last_seen': last_seen_aware.isoformat() if last_seen_aware else None,
            'is_online': is_online,
        })

    # Онлайн первыми, внутри — по убыванию last_seen (новейшие выше).
    # Стабильная сортировка: ключи применяем от вторичного к первичному.
    rows.sort(key=lambda r: r['last_seen'] or '', reverse=True)
    rows.sort(key=lambda r: 0 if r['is_online'] else 1)

    return jsonify({
        'success': True,
        'users': rows,
        'online_threshold_seconds': ONLINE_THRESHOLD_SECONDS,
        'server_time': now.isoformat(),
    }), 200
