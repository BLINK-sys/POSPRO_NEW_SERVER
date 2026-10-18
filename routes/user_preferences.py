"""
Пользовательские настройки UI: GET/PUT /api/user-prefs/<key>.

Хранит JSONB-значение на пару (user_id, key). Используется фронтом
для сохранения состояний фильтров/вьюх (пример: `deals_canvas` —
фильтры канбана сделок).
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models.user_preference import UserPreference


user_prefs_bp = Blueprint('user_prefs', __name__)


def _me() -> int | None:
    try:
        return int(get_jwt_identity() or 0) or None
    except (TypeError, ValueError):
        return None


@user_prefs_bp.route('/user-prefs/<key>', methods=['GET'], strict_slashes=False)
@jwt_required()
def get_pref(key: str):
    uid = _me()
    if not uid:
        return jsonify({'error': 'Нет доступа'}), 403
    row = UserPreference.query.filter_by(user_id=uid, key=key).first()
    return jsonify({'success': True, 'value': row.value if row else None}), 200


@user_prefs_bp.route('/user-prefs/<key>', methods=['PUT'], strict_slashes=False)
@jwt_required()
def put_pref(key: str):
    uid = _me()
    if not uid:
        return jsonify({'error': 'Нет доступа'}), 403
    data = request.get_json(silent=True) or {}
    value = data.get('value')
    if value is None:
        return jsonify({'error': 'value обязателен'}), 400

    row = UserPreference.query.filter_by(user_id=uid, key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(UserPreference(user_id=uid, key=key, value=value))
    db.session.commit()
    return jsonify({'success': True, 'value': value}), 200
