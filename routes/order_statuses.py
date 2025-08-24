from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models import OrderStatus
from extensions import db

order_statuses_bp = Blueprint('order_statuses', __name__)


@order_statuses_bp.route('/order-statuses', methods=['GET'])
@jwt_required()
def get_order_statuses():
    """Получить все статусы заказов"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        statuses = OrderStatus.query.order_by(OrderStatus.order, OrderStatus.id).all()
        
        return jsonify({
            'success': True,
            'data': [status.to_dict() for status in statuses]
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении статусов: {str(e)}'
        }), 500


@order_statuses_bp.route('/order-statuses', methods=['POST'])
@jwt_required()
def create_order_status():
    """Создать новый статус заказа"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        
        # Валидация обязательных полей
        required_fields = ['name', 'background_color', 'text_color']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'message': f'Поле {field} обязательно для заполнения'
                }), 400



        # Валидация цветов (должны быть в формате hex)
        for color_field in ['background_color', 'text_color']:
            color = data.get(color_field, '')
            if not color.startswith('#') or len(color) != 7:
                return jsonify({
                    'success': False,
                    'message': f'Цвет {color_field} должен быть в формате hex (#RRGGBB)'
                }), 400

        # Получаем максимальный порядок для нового статуса
        max_order = db.session.query(db.func.max(OrderStatus.order)).scalar() or 0
        
        # Создание нового статуса
        status = OrderStatus(
            name=data['name'],
            description=data.get('description', ''),
            background_color=data['background_color'],
            text_color=data['text_color'],
            order=max_order + 1,  # Новый статус в конец списка
            is_active=data.get('is_active', True),
            is_final=data.get('is_final', False)
        )

        db.session.add(status)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Статус заказа создан успешно',
            'data': status.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании статуса: {str(e)}'
        }), 500


@order_statuses_bp.route('/order-statuses/<int:status_id>', methods=['PUT'])
@jwt_required()
def update_order_status(status_id):
    """Обновить статус заказа"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        status = OrderStatus.query.get(status_id)
        if not status:
            return jsonify({
                'success': False,
                'message': 'Статус не найден'
            }), 404

        data = request.get_json()



        # Валидация цветов
        for color_field in ['background_color', 'text_color']:
            if color_field in data:
                color = data[color_field]
                if not color.startswith('#') or len(color) != 7:
                    return jsonify({
                        'success': False,
                        'message': f'Цвет {color_field} должен быть в формате hex (#RRGGBB)'
                    }), 400

        # Обновление полей (порядок изменяется только через drag & drop)
        for field in ['name', 'description', 'background_color', 'text_color', 'is_active', 'is_final']:
            if field in data:
                setattr(status, field, data[field])

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Статус заказа обновлен успешно',
            'data': status.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении статуса: {str(e)}'
        }), 500


@order_statuses_bp.route('/order-statuses/<int:status_id>', methods=['DELETE'])
@jwt_required()
def delete_order_status(status_id):
    """Удалить статус заказа"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        status = OrderStatus.query.get(status_id)
        if not status:
            return jsonify({
                'success': False,
                'message': 'Статус не найден'
            }), 404

        # Проверяем, не используется ли статус в заказах
        # Пока просто удаляем, но в будущем можно добавить проверку
        
        db.session.delete(status)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Статус заказа удален успешно'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении статуса: {str(e)}'
        }), 500


@order_statuses_bp.route('/order-statuses/public', methods=['GET'])
def get_public_order_statuses():
    """Получить активные статусы заказов для публичного использования"""
    try:
        statuses = OrderStatus.query.filter_by(is_active=True).order_by(OrderStatus.order, OrderStatus.id).all()
        
        return jsonify({
            'success': True,
            'data': [status.to_dict() for status in statuses]
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении статусов: {str(e)}'
        }), 500


@order_statuses_bp.route('/order-statuses/reorder', methods=['PUT'])
@jwt_required()
def reorder_statuses():
    """Изменить порядок статусов заказов"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        status_ids = data.get('status_ids', [])
        
        if not status_ids:
            return jsonify({
                'success': False,
                'message': 'Список ID статусов не предоставлен'
            }), 400

        # Обновляем порядок для каждого статуса
        for index, status_id in enumerate(status_ids):
            status = OrderStatus.query.get(status_id)
            if status:
                status.order = index + 1
        
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Порядок статусов обновлен успешно'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении порядка: {str(e)}'
        }), 500
