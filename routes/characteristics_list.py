from flask import Blueprint, request, jsonify
from extensions import db
from models.characteristics_list import CharacteristicsList
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy.exc import IntegrityError

characteristics_list_bp = Blueprint('characteristics_list', __name__)

@characteristics_list_bp.route('/', methods=['GET'])
@jwt_required()
def get_characteristics_list():
    """Получить список всех характеристик"""
    try:
        characteristics = CharacteristicsList.query.all()
        return jsonify({
            'success': True,
            'data': [char.to_dict() for char in characteristics]
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении списка характеристик: {str(e)}'
        }), 500

@characteristics_list_bp.route('/<int:characteristic_id>', methods=['GET'])
@jwt_required()
def get_characteristic(characteristic_id):
    """Получить характеристику по ID"""
    try:
        characteristic = CharacteristicsList.query.get(characteristic_id)
        if not characteristic:
            return jsonify({
                'success': False,
                'message': 'Характеристика не найдена'
            }), 404
        
        return jsonify({
            'success': True,
            'data': characteristic.to_dict()
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении характеристики: {str(e)}'
        }), 500

@characteristics_list_bp.route('/', methods=['POST'])
@jwt_required()
def create_characteristic():
    """Создать новую характеристику (только для админов)"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403
        data = request.get_json()
        
        if not data or 'characteristic_key' not in data:
            return jsonify({
                'success': False,
                'message': 'Отсутствует обязательное поле characteristic_key'
            }), 400
        
        characteristic_key = data['characteristic_key'].strip()
        unit_of_measurement = data.get('unit_of_measurement', '').strip() if data.get('unit_of_measurement') else None
        
        if not characteristic_key:
            return jsonify({
                'success': False,
                'message': 'characteristic_key не может быть пустым'
            }), 400
        
        # Проверяем, не существует ли уже такая характеристика
        existing = CharacteristicsList.query.filter_by(characteristic_key=characteristic_key).first()
        if existing:
            return jsonify({
                'success': False,
                'message': 'Характеристика с таким ключом уже существует'
            }), 400
        
        new_characteristic = CharacteristicsList(
            characteristic_key=characteristic_key,
            unit_of_measurement=unit_of_measurement
        )
        
        db.session.add(new_characteristic)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика успешно создана',
            'data': new_characteristic.to_dict()
        }), 201
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Характеристика с таким ключом уже существует'
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании характеристики: {str(e)}'
        }), 500

@characteristics_list_bp.route('/<int:characteristic_id>', methods=['PUT'])
@jwt_required()
def update_characteristic(characteristic_id):
    """Обновить характеристику (только для админов)"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403
        characteristic = CharacteristicsList.query.get(characteristic_id)
        if not characteristic:
            return jsonify({
                'success': False,
                'message': 'Характеристика не найдена'
            }), 404
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'Отсутствуют данные для обновления'
            }), 400
        
        # Обновляем поля
        if 'characteristic_key' in data:
            new_key = data['characteristic_key'].strip()
            if not new_key:
                return jsonify({
                    'success': False,
                    'message': 'characteristic_key не может быть пустым'
                }), 400
            
            # Проверяем, не существует ли уже такая характеристика (кроме текущей)
            existing = CharacteristicsList.query.filter(
                CharacteristicsList.characteristic_key == new_key,
                CharacteristicsList.id != characteristic_id
            ).first()
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'Характеристика с таким ключом уже существует'
                }), 400
            
            characteristic.characteristic_key = new_key
        
        if 'unit_of_measurement' in data:
            characteristic.unit_of_measurement = data['unit_of_measurement'].strip() if data['unit_of_measurement'] else None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика успешно обновлена',
            'data': characteristic.to_dict()
        }), 200
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Характеристика с таким ключом уже существует'
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении характеристики: {str(e)}'
        }), 500

@characteristics_list_bp.route('/<int:characteristic_id>', methods=['DELETE'])
@jwt_required()
def delete_characteristic(characteristic_id):
    """Удалить характеристику (только для админов)"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403
        characteristic = CharacteristicsList.query.get(characteristic_id)
        if not characteristic:
            return jsonify({
                'success': False,
                'message': 'Характеристика не найдена'
            }), 404
        
        db.session.delete(characteristic)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика успешно удалена'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении характеристики: {str(e)}'
        }), 500
