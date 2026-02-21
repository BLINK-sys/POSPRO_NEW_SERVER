from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models.kp_settings import KPSettings
from extensions import db

kp_settings_bp = Blueprint('kp_settings', __name__)


@kp_settings_bp.route('/kp-settings', methods=['GET'])
@jwt_required()
def get_kp_settings():
    """Получить настройки КП для текущего пользователя"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        # КП доступно только админам
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPSettings.query.filter_by(user_id=user_id, user_role=role).first()

        if not record:
            return jsonify({'success': True, 'settings': None}), 200

        return jsonify({'success': True, 'settings': record.settings}), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_settings_bp.route('/kp-settings', methods=['PUT'])
@jwt_required()
def save_kp_settings():
    """Сохранить/обновить настройки КП для текущего пользователя"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        data = request.get_json()
        if not data or 'settings' not in data:
            return jsonify({'error': 'Поле settings обязательно'}), 400

        settings = data['settings']

        record = KPSettings.query.filter_by(user_id=user_id, user_role=role).first()

        if record:
            record.settings = settings
            record.updated_at = db.func.now()
        else:
            record = KPSettings(
                user_id=user_id,
                user_role=role,
                settings=settings,
            )
            db.session.add(record)

        db.session.commit()

        return jsonify({'success': True, 'message': 'Настройки сохранены'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
