"""
Endpoints для шаринга КП и super-admin доступа.

Шаринг (от менеджера менеджеру):
  POST   /api/kp-history/<id>/share          — добавить получателя
  DELETE /api/kp-history/<id>/share/<uid>    — отозвать
  GET    /api/kp-history/<id>/shares         — список получателей конкретного КП

Super-admin (выдаёт только owner):
  GET    /api/admin/kp-super-admin-access         — список + is_owner
  PUT    /api/admin/kp-super-admin-access         — обновить список (only owner)
  GET    /api/admin/kp-super-admin-access/check   — для гейтинга UI (любой)

Helper'ы для проверки доступа экспортируются для использования в kp_history.py.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from extensions import db
from models.kp_history import KPHistory
from models.kp_share import KPShare, KPSuperAdminAccess
from models.systemuser import SystemUser
from routes.auth import is_owner_user

kp_share_bp = Blueprint('kp_share', __name__)


# ────────────────────────────── helpers ──────────────────────────────

def is_super_admin(user_id) -> bool:
    """
    True если пользователь видит ВСЕ КП всех юзеров с полным доступом.
    Это либо owner системы, либо тот кому owner выдал грант через
    раздел «Управление КП».
    """
    if user_id is None:
        return False
    if is_owner_user(user_id):
        return True
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return False
    cfg = KPSuperAdminAccess.get_or_create()
    allowed = list(cfg.allowed_user_ids or [])
    return uid in allowed


def kp_access_level(viewer_id, kp: KPHistory) -> str | None:
    """
    Возвращает уровень доступа viewer'а к конкретному КП:
        'owner'  — viewer создал этот КП. Полный доступ + удаление + шаринг
        'edit'   — расшарили с edit ИЛИ viewer — super-admin
        'view'   — расшарили с view
        None     — доступа нет (КП скрыт от viewer'а)
    """
    if viewer_id is None or kp is None:
        return None
    try:
        vid = int(viewer_id)
    except (ValueError, TypeError):
        return None

    if kp.user_id == vid:
        return 'owner'

    # Super-admin видит всё с правом редактирования (но не удаления —
    # это правило прописано в delete-handler'е kp_history.py).
    if is_super_admin(vid):
        return 'edit'

    share = KPShare.query.filter_by(
        kp_history_id=kp.id, shared_with_user_id=vid
    ).first()
    if not share:
        return None
    return share.access_level if share.access_level in ('view', 'edit') else 'view'


def can_share_kp(viewer_id, kp: KPHistory) -> bool:
    """Шарить может только владелец КП или super-admin."""
    if viewer_id is None or kp is None:
        return False
    try:
        vid = int(viewer_id)
    except (ValueError, TypeError):
        return False
    return kp.user_id == vid or is_super_admin(vid)


def _check_admin_role():
    """Гард для admin-роутов: пускает только system/admin JWT."""
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


# ────────────────────────────── share endpoints ──────────────────────

@kp_share_bp.route('/kp-history/<int:kp_id>/share', methods=['POST'])
@jwt_required()
def share_kp(kp_id):
    """
    Поделиться КП с другим системным пользователем.
    Body: { target_user_id: int, access_level: 'view' | 'edit' }
    """
    err = _check_admin_role()
    if err:
        return err

    viewer_id = int(get_jwt_identity())
    kp = KPHistory.query.get(kp_id)
    if not kp:
        return jsonify({'error': 'КП не найдено'}), 404
    if not can_share_kp(viewer_id, kp):
        return jsonify({'error': 'Только владелец КП или super-admin может им поделиться'}), 403

    data = request.get_json() or {}
    target_id = data.get('target_user_id')
    access_level = (data.get('access_level') or 'view').strip()

    if access_level not in ('view', 'edit'):
        return jsonify({'error': 'access_level должен быть view или edit'}), 400
    try:
        target_id = int(target_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'target_user_id обязателен'}), 400
    if target_id == kp.user_id:
        return jsonify({'error': 'Нельзя поделиться с владельцем КП'}), 400
    if not SystemUser.query.get(target_id):
        return jsonify({'error': 'Целевой пользователь не найден'}), 404

    # Если шарить уже есть — обновляем уровень
    existing = KPShare.query.filter_by(
        kp_history_id=kp_id, shared_with_user_id=target_id
    ).first()
    if existing:
        existing.access_level = access_level
        existing.created_by = viewer_id
        db.session.commit()
        return jsonify({'success': True, 'data': existing.to_dict(), 'updated': True}), 200

    share = KPShare(
        kp_history_id=kp_id,
        shared_with_user_id=target_id,
        access_level=access_level,
        created_by=viewer_id,
    )
    db.session.add(share)
    db.session.commit()
    return jsonify({'success': True, 'data': share.to_dict()}), 201


@kp_share_bp.route('/kp-history/<int:kp_id>/share/<int:target_user_id>', methods=['DELETE'])
@jwt_required()
def revoke_kp_share(kp_id, target_user_id):
    """Отозвать доступ. Может только владелец КП или super-admin."""
    err = _check_admin_role()
    if err:
        return err
    viewer_id = int(get_jwt_identity())
    kp = KPHistory.query.get(kp_id)
    if not kp:
        return jsonify({'error': 'КП не найдено'}), 404
    if not can_share_kp(viewer_id, kp):
        return jsonify({'error': 'Доступ запрещён'}), 403
    share = KPShare.query.filter_by(
        kp_history_id=kp_id, shared_with_user_id=target_user_id
    ).first()
    if not share:
        return jsonify({'error': 'Шаринг не найден'}), 404
    db.session.delete(share)
    db.session.commit()
    return jsonify({'success': True}), 200


@kp_share_bp.route('/kp-history/<int:kp_id>/shares', methods=['GET'])
@jwt_required()
def list_kp_shares(kp_id):
    """Список текущих получателей доступа к этому КП. Видит владелец или super-admin."""
    err = _check_admin_role()
    if err:
        return err
    viewer_id = int(get_jwt_identity())
    kp = KPHistory.query.get(kp_id)
    if not kp:
        return jsonify({'error': 'КП не найдено'}), 404
    if not can_share_kp(viewer_id, kp):
        return jsonify({'error': 'Доступ запрещён'}), 403

    shares = KPShare.query.filter_by(kp_history_id=kp_id).all()
    # Денормализуем имя получателя для UI (один SQL — не страшно)
    target_ids = [s.shared_with_user_id for s in shares]
    users_by_id = {
        u.id: {'id': u.id, 'email': u.email, 'full_name': u.full_name}
        for u in SystemUser.query.filter(SystemUser.id.in_(target_ids)).all()
    } if target_ids else {}

    return jsonify({
        'success': True,
        'shares': [{
            **s.to_dict(),
            'target': users_by_id.get(s.shared_with_user_id),
        } for s in shares]
    }), 200


@kp_share_bp.route('/kp-share/system-users', methods=['GET'])
@jwt_required()
def list_share_targets():
    """
    Список системных пользователей для модалки «Поделиться» — все system_users
    кроме самого вызывающего. Owner тоже включается (вдруг кому-то надо
    явно расшарить КП в видимость owner'а — хотя owner и так видит).
    """
    err = _check_admin_role()
    if err:
        return err
    viewer_id = int(get_jwt_identity())
    users = SystemUser.query.filter(SystemUser.id != viewer_id).order_by(SystemUser.full_name).all()
    return jsonify({
        'success': True,
        'users': [
            {'id': u.id, 'email': u.email, 'full_name': u.full_name}
            for u in users
        ]
    }), 200


# ──────────────────────── super-admin access ─────────────────────────

@kp_share_bp.route('/admin/kp-super-admin-access', methods=['GET'])
@jwt_required()
def get_kp_super_admin_access():
    """
    Полная конфигурация супер-админ доступа. Видит только owner —
    остальные системники видят только свой статус через `/check`.
    """
    err = _check_admin_role()
    if err:
        return err
    viewer_id = int(get_jwt_identity())
    if not is_owner_user(viewer_id):
        return jsonify({'error': 'Только владелец системы может управлять этим разделом'}), 403

    cfg = KPSuperAdminAccess.get_or_create()
    # Список всех системников для UI чекбоксов (owner исключим в UI)
    users = SystemUser.query.order_by(SystemUser.full_name).all()
    return jsonify({
        'success': True,
        'access': cfg.to_dict(),
        'system_users': [
            {
                'id': u.id,
                'email': u.email,
                'full_name': u.full_name,
                'is_owner': bool(u.is_owner),
            }
            for u in users
        ],
    }), 200


@kp_share_bp.route('/admin/kp-super-admin-access', methods=['PUT'])
@jwt_required()
def put_kp_super_admin_access():
    """Обновить список super-admin'ов. Только owner."""
    err = _check_admin_role()
    if err:
        return err
    viewer_id = int(get_jwt_identity())
    if not is_owner_user(viewer_id):
        return jsonify({'error': 'Только владелец системы может управлять этим разделом'}), 403

    data = request.get_json() or {}
    raw_ids = data.get('allowed_user_ids') or []
    if not isinstance(raw_ids, list):
        return jsonify({'error': 'allowed_user_ids должен быть массивом'}), 400

    # Нормализуем: int'ы, без owner'ов (они и так видят), без дубликатов
    cleaned = []
    seen = set()
    for raw in raw_ids:
        try:
            uid = int(raw)
        except (ValueError, TypeError):
            continue
        if uid in seen:
            continue
        # Owner'а не сохраняем в списке — у него уже хардкодный полный доступ
        if is_owner_user(uid):
            continue
        if not SystemUser.query.get(uid):
            continue
        seen.add(uid)
        cleaned.append(uid)

    cfg = KPSuperAdminAccess.get_or_create()
    cfg.allowed_user_ids = cleaned
    cfg.updated_at = datetime.utcnow()
    su = SystemUser.query.get(viewer_id)
    cfg.updated_by_email = su.email if su else None
    db.session.commit()

    return jsonify({'success': True, 'access': cfg.to_dict()}), 200


@kp_share_bp.route('/admin/kp-super-admin-access/check', methods=['GET'])
@jwt_required()
def check_kp_super_admin_access():
    """
    Возвращает статус для текущего пользователя — есть ли у него super-admin
    доступ. Используется UI для гейтинга кнопок/фильтра.
    """
    err = _check_admin_role()
    if err:
        return err
    viewer_id = int(get_jwt_identity())
    return jsonify({
        'success': True,
        'is_owner': is_owner_user(viewer_id),
        'is_super_admin': is_super_admin(viewer_id),
    }), 200
