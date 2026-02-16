from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.product_availability_status import ProductAvailabilityStatus

product_availability_statuses_bp = Blueprint('product_availability_statuses', __name__)


# 🔹 Получить список статусов наличия
@product_availability_statuses_bp.route('/product-availability-statuses', methods=['GET'])
@jwt_required()
def get_product_availability_statuses():
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        statuses = ProductAvailabilityStatus.query.order_by(ProductAvailabilityStatus.order).all()
        return jsonify([status.to_dict() for status in statuses])
    except Exception as e:
        return jsonify({'error': f'Ошибка получения статусов: {str(e)}'}), 500


# 🔹 Создать новый статус наличия
@product_availability_statuses_bp.route('/product-availability-statuses', methods=['POST'])
@jwt_required()
def create_product_availability_status():
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        print("Полученные данные:", data)
        
        # Валидация данных
        required_fields = ['status_name', 'condition_operator', 'condition_value']
        for field in required_fields:
            if field not in data or (field != 'condition_value' and not data[field]):
                return jsonify({'error': f'Поле {field} обязательно'}), 400
        
        # Отдельная проверка для condition_value (может быть 0)
        if 'condition_value' not in data:
            return jsonify({'error': 'Поле condition_value обязательно'}), 400
        
        # Проверка оператора
        valid_operators = ['>', '<', '=', '>=', '<=']
        if data['condition_operator'] not in valid_operators:
            return jsonify({'error': 'Неверный оператор. Допустимые значения: >, <, =, >=, <='}), 400
        
        # Проверка значения
        try:
            condition_value = int(data['condition_value'])
            if condition_value < 0:
                return jsonify({'error': 'Значение должно быть неотрицательным'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Значение должно быть числом'}), 400
        
        # Получаем следующий порядок
        max_order = db.session.query(db.func.max(ProductAvailabilityStatus.order)).scalar() or 0
        
        # Валидация supplier_id (если указан)
        supplier_id = data.get('supplier_id')
        if supplier_id is not None:
            supplier_id = int(supplier_id) if supplier_id else None

        new_status = ProductAvailabilityStatus(
            status_name=data['status_name'],
            condition_operator=data['condition_operator'],
            condition_value=condition_value,
            background_color=data.get('background_color', '#ffffff'),
            text_color=data.get('text_color', '#000000'),
            order=max_order + 1,
            active=data.get('active', True),
            supplier_id=supplier_id
        )
        
        db.session.add(new_status)
        db.session.commit()
        
        return jsonify({
            'message': 'Статус наличия создан успешно',
            'status': new_status.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Ошибка создания статуса: {str(e)}'}), 500


# 🔹 Обновить статус наличия
@product_availability_statuses_bp.route('/product-availability-statuses/<int:status_id>', methods=['PUT'])
@jwt_required()
def update_product_availability_status(status_id):
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        status = ProductAvailabilityStatus.query.get(status_id)
        if not status:
            return jsonify({'error': 'Статус не найден'}), 404
        
        data = request.get_json()
        
        # Валидация данных
        if 'status_name' in data and not data['status_name']:
            return jsonify({'error': 'Название статуса не может быть пустым'}), 400
        
        if 'condition_operator' in data:
            valid_operators = ['>', '<', '=', '>=', '<=']
            if data['condition_operator'] not in valid_operators:
                return jsonify({'error': 'Неверный оператор. Допустимые значения: >, <, =, >=, <='}), 400
        
        if 'condition_value' in data:
            try:
                condition_value = int(data['condition_value'])
                if condition_value < 0:
                    return jsonify({'error': 'Значение должно быть неотрицательным'}), 400
                status.condition_value = condition_value
            except (ValueError, TypeError):
                return jsonify({'error': 'Значение должно быть числом'}), 400
        
        # Обновляем поля
        if 'status_name' in data:
            status.status_name = data['status_name']
        if 'condition_operator' in data:
            status.condition_operator = data['condition_operator']
        if 'background_color' in data:
            status.background_color = data['background_color']
        if 'text_color' in data:
            status.text_color = data['text_color']
        if 'active' in data:
            status.active = data['active']
        if 'supplier_id' in data:
            status.supplier_id = int(data['supplier_id']) if data['supplier_id'] else None
        
        db.session.commit()
        
        return jsonify({
            'message': 'Статус наличия обновлен успешно',
            'status': status.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Ошибка обновления статуса: {str(e)}'}), 500


# 🔹 Удалить статус наличия
@product_availability_statuses_bp.route('/product-availability-statuses/<int:status_id>', methods=['DELETE'])
@jwt_required()
def delete_product_availability_status(status_id):
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        status = ProductAvailabilityStatus.query.get(status_id)
        if not status:
            return jsonify({'error': 'Статус не найден'}), 404
        
        db.session.delete(status)
        db.session.commit()
        
        return jsonify({'message': 'Статус наличия удален успешно'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Ошибка удаления статуса: {str(e)}'}), 500


# 🔹 Изменить порядок статусов
@product_availability_statuses_bp.route('/product-availability-statuses/reorder', methods=['POST'])
@jwt_required()
def reorder_product_availability_statuses():
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        if 'statuses' not in data or not isinstance(data['statuses'], list):
            return jsonify({'error': 'Неверный формат данных'}), 400
        
        for item in data['statuses']:
            if 'id' not in item or 'order' not in item:
                continue
            
            status = ProductAvailabilityStatus.query.get(item['id'])
            if status:
                status.order = item['order']
        
        db.session.commit()
        return jsonify({'message': 'Порядок статусов обновлен успешно'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Ошибка обновления порядка: {str(e)}'}), 500


# 🔹 Получить статус для товара по количеству (публичный эндпоинт)
@product_availability_statuses_bp.route('/product-availability-statuses/check/<int:quantity>', methods=['GET'])
def get_status_for_quantity(quantity):
    try:
        # Получаем активные статусы, отсортированные по порядку
        statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()
        
        # Находим подходящий статус
        for status in statuses:
            if status.check_condition(quantity):
                return jsonify({
                    'status': status.to_dict(),
                    'formula': status.get_formula_display()
                })
        
        # Если не найден подходящий статус, возвращаем null
        return jsonify({'status': None, 'formula': None})
        
    except Exception as e:
        return jsonify({'error': f'Ошибка получения статуса: {str(e)}'}), 500
