from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models.kp_history import KPHistory
from extensions import db

kp_history_bp = Blueprint('kp_history', __name__)


@kp_history_bp.route('/kp-history', methods=['GET'])
@jwt_required()
def get_kp_history_list():
    """Список сохранённых КП текущего пользователя (краткий формат)"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        records = KPHistory.query.filter_by(
            user_id=user_id, user_role=role
        ).order_by(KPHistory.created_at.desc()).all()

        return jsonify({
            'success': True,
            'history': [r.to_dict(short=True) for r in records]
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history/<int:history_id>', methods=['GET'])
@jwt_required()
def get_kp_history_item(history_id):
    """Получить полные данные одного КП из истории"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPHistory.query.filter_by(
            id=history_id, user_id=user_id, user_role=role
        ).first()

        if not record:
            return jsonify({'error': 'КП не найдено'}), 404

        return jsonify({
            'success': True,
            'data': record.to_dict(short=False)
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history', methods=['POST'])
@jwt_required()
def save_kp_history():
    """Сохранить КП в историю"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        name = data.get('name', '').strip()
        items = data.get('items', [])
        settings = data.get('settings', {})
        total_amount = data.get('total_amount', 0)

        if not name:
            name = 'КП без названия'

        calculator_data = data.get('calculator_data', None)

        record = KPHistory(
            user_id=user_id,
            user_role=role,
            name=name,
            items=items,
            settings=settings,
            total_amount=total_amount,
            calculator_data=calculator_data,
        )
        db.session.add(record)
        db.session.commit()

        return jsonify({
            'success': True,
            'id': record.id,
            'message': 'КП сохранено в историю'
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history/<int:history_id>', methods=['PUT'])
@jwt_required()
def update_kp_history(history_id):
    """Обновить существующее КП в истории"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPHistory.query.filter_by(
            id=history_id, user_id=user_id, user_role=role
        ).first()

        if not record:
            return jsonify({'error': 'КП не найдено'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        if 'name' in data:
            record.name = data['name'].strip() or record.name
        if 'items' in data:
            record.items = data['items']
        if 'settings' in data:
            record.settings = data['settings']
        if 'total_amount' in data:
            record.total_amount = data['total_amount']
        if 'calculator_data' in data:
            record.calculator_data = data['calculator_data']

        db.session.commit()

        return jsonify({
            'success': True,
            'id': record.id,
            'message': 'КП обновлено'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history/<int:history_id>', methods=['DELETE'])
@jwt_required()
def delete_kp_history(history_id):
    """Удалить КП из истории"""
    try:
        user_id = int(get_jwt_identity())
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')

        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPHistory.query.filter_by(
            id=history_id, user_id=user_id, user_role=role
        ).first()

        if not record:
            return jsonify({'error': 'КП не найдено'}), 404

        db.session.delete(record)
        db.session.commit()

        return jsonify({'success': True, 'message': 'КП удалено'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
