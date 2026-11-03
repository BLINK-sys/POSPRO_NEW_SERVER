"""
Техническое обслуживание сайта (owner-only).

- CRUD заготовок (`/api/admin/maintenance/notices`) — только для owner.
- Переключатели вкл/выкл (`/api/admin/maintenance/mode/enable|disable|status`)
  — тоже только owner.
- Публичный статус `/api/public/maintenance-status` — доступен без auth,
  используется и клиентом (middleware), и страницей-заглушкой.
  Отдаёт только `{enabled, notice:{title,body}}`, без лишних деталей.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models.maintenance import MaintenanceNotice, SiteMode
from routes.auth import is_owner_user

maintenance_bp = Blueprint('maintenance', __name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _require_owner():
    try:
        uid = get_jwt_identity()
    except Exception:
        return jsonify({'error': 'Не авторизован'}), 401
    if not uid or not is_owner_user(uid):
        return jsonify({'error': 'Доступ только для владельца'}), 403
    return None


def _get_or_init_mode() -> SiteMode:
    """Гарантирует наличие одной записи id=1 в site_mode."""
    sm = SiteMode.query.get(1)
    if sm is None:
        sm = SiteMode(id=1, is_maintenance=False)
        db.session.add(sm)
        db.session.commit()
    return sm


def _mode_dict(sm: SiteMode) -> dict:
    return {
        'is_maintenance': bool(sm.is_maintenance),
        'notice_id': sm.notice_id,
        'notice': sm.notice.to_dict() if sm.notice else None,
        'started_at': sm.started_at.isoformat() if sm.started_at else None,
        'started_by_user_id': sm.started_by_user_id,
        'updated_at': sm.updated_at.isoformat() if sm.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Публичный статус (без auth, читают middleware и страница /maintenance)
# ---------------------------------------------------------------------------

@maintenance_bp.route('/api/public/maintenance-status', methods=['GET'])
def public_status():
    sm = _get_or_init_mode()
    if not sm.is_maintenance:
        return jsonify({'enabled': False, 'notice': None}), 200
    return jsonify({
        'enabled': True,
        'notice': {
            'title': sm.notice.title if sm.notice else 'Магазин временно недоступен',
            'body': sm.notice.body if sm.notice else '',
        },
    }), 200


# ---------------------------------------------------------------------------
# Админский (owner only) — CRUD заготовок
# ---------------------------------------------------------------------------

@maintenance_bp.route('/api/admin/maintenance/notices', methods=['GET'])
@jwt_required()
def list_notices():
    err = _require_owner()
    if err:
        return err
    rows = MaintenanceNotice.query.order_by(MaintenanceNotice.id.desc()).all()
    return jsonify({'notices': [n.to_dict() for n in rows]}), 200


@maintenance_bp.route('/api/admin/maintenance/notices', methods=['POST'])
@jwt_required()
def create_notice():
    err = _require_owner()
    if err:
        return err
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title:
        return jsonify({'error': 'title обязателен'}), 400
    n = MaintenanceNotice(title=title[:255], body=body)
    db.session.add(n)
    db.session.commit()
    return jsonify({'notice': n.to_dict()}), 201


@maintenance_bp.route('/api/admin/maintenance/notices/<int:nid>', methods=['PUT'])
@jwt_required()
def update_notice(nid):
    err = _require_owner()
    if err:
        return err
    n = MaintenanceNotice.query.get_or_404(nid)
    data = request.get_json() or {}
    if 'title' in data:
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'error': 'title не может быть пустым'}), 400
        n.title = title[:255]
    if 'body' in data:
        n.body = (data.get('body') or '').strip()
    n.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'notice': n.to_dict()}), 200


@maintenance_bp.route('/api/admin/maintenance/notices/<int:nid>', methods=['DELETE'])
@jwt_required()
def delete_notice(nid):
    err = _require_owner()
    if err:
        return err
    n = MaintenanceNotice.query.get_or_404(nid)
    # Если удаляем ту, что сейчас активна — автоматом включим «выключение»
    # на fallback-сообщение, чтоб страница не упала. Проще: если
    # is_maintenance=True и notice_id=этот, то обнулить notice_id (fallback
    # текст в public_status уже предусмотрен).
    sm = _get_or_init_mode()
    if sm.notice_id == nid:
        sm.notice_id = None
        sm.updated_at = datetime.utcnow()
    db.session.delete(n)
    db.session.commit()
    return jsonify({'success': True}), 200


# ---------------------------------------------------------------------------
# Владельческий — вкл/выкл магазина и статус
# ---------------------------------------------------------------------------

@maintenance_bp.route('/api/admin/maintenance/mode', methods=['GET'])
@jwt_required()
def mode_status():
    err = _require_owner()
    if err:
        return err
    sm = _get_or_init_mode()
    return jsonify(_mode_dict(sm)), 200


@maintenance_bp.route('/api/admin/maintenance/mode/enable', methods=['POST'])
@jwt_required()
def mode_enable():
    err = _require_owner()
    if err:
        return err
    data = request.get_json() or {}
    notice_id = data.get('notice_id')
    if not notice_id:
        return jsonify({'error': 'notice_id обязателен'}), 400
    n = MaintenanceNotice.query.get(notice_id)
    if not n:
        return jsonify({'error': 'Заготовка не найдена'}), 404
    sm = _get_or_init_mode()
    sm.is_maintenance = True
    sm.notice_id = n.id
    sm.started_at = datetime.utcnow()
    sm.started_by_user_id = get_jwt_identity()
    sm.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_mode_dict(sm)), 200


@maintenance_bp.route('/api/admin/maintenance/mode/disable', methods=['POST'])
@jwt_required()
def mode_disable():
    err = _require_owner()
    if err:
        return err
    sm = _get_or_init_mode()
    sm.is_maintenance = False
    # notice_id и started_at не затираем — может понадобиться в UI как
    # «последнее включение было такого-то». updated_at трогаем.
    sm.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_mode_dict(sm)), 200
