"""
API маршруты для работы со справочником характеристик
"""

from flask import Blueprint, request, jsonify
from extensions import db
from models import CharacteristicsList
from utils.jwt import token_required, admin_required
from sqlalchemy.exc import SQLAlchemyError

characteristics_bp = Blueprint('characteristics_list', __name__)

@characteristics_bp.route('/api/characteristics', methods=['GET'])
@token_required
def get_characteristics(current_user):
    """Получить все характеристики"""
    try:
        characteristics = CharacteristicsList.get_all()
        return jsonify({
            'success': True,
            'data': [char.to_dict() for char in characteristics]
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении характеристик: {str(e)}'
        }), 500

@characteristics_bp.route('/api/characteristics/<int:characteristic_id>', methods=['GET'])
@token_required
def get_characteristic(current_user, characteristic_id):
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

@characteristics_bp.route('/api/characteristics', methods=['POST'])
@token_required
@admin_required
def create_characteristic(current_user):
    """Создать новую характеристику (только для админов)"""
    try:
        data = request.get_json()
        
        if not data or 'characteristic_key' not in data:
            return jsonify({
                'success': False,
                'message': 'Отсутствует обязательное поле characteristic_key'
            }), 400
        
        # Проверяем, не существует ли уже такая характеристика
        existing = CharacteristicsList.get_by_key(data['characteristic_key'])
        if existing:
            return jsonify({
                'success': False,
                'message': 'Характеристика с таким ключом уже существует'
            }), 400
        
        characteristic = CharacteristicsList.create(
            characteristic_key=data['characteristic_key'],
            unit_of_measurement=data.get('unit_of_measurement')
        )
        
        return jsonify({
            'success': True,
            'data': characteristic.to_dict(),
            'message': 'Характеристика успешно создана'
        }), 201
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка базы данных: {str(e)}'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании характеристики: {str(e)}'
        }), 500

@characteristics_bp.route('/api/characteristics/<int:characteristic_id>', methods=['PUT'])
@token_required
@admin_required
def update_characteristic(current_user, characteristic_id):
    """Обновить характеристику (только для админов)"""
    try:
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
        
        # Проверяем уникальность ключа, если он изменяется
        if 'characteristic_key' in data and data['characteristic_key'] != characteristic.characteristic_key:
            existing = CharacteristicsList.get_by_key(data['characteristic_key'])
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'Характеристика с таким ключом уже существует'
                }), 400
        
        characteristic.update(
            characteristic_key=data.get('characteristic_key'),
            unit_of_measurement=data.get('unit_of_measurement')
        )
        
        return jsonify({
            'success': True,
            'data': characteristic.to_dict(),
            'message': 'Характеристика успешно обновлена'
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка базы данных: {str(e)}'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении характеристики: {str(e)}'
        }), 500

@characteristics_bp.route('/api/characteristics/<int:characteristic_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_characteristic(current_user, characteristic_id):
    """Удалить характеристику (только для админов)"""
    try:
        characteristic = CharacteristicsList.query.get(characteristic_id)
        if not characteristic:
            return jsonify({
                'success': False,
                'message': 'Характеристика не найдена'
            }), 404
        
        characteristic.delete()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика успешно удалена'
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка базы данных: {str(e)}'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении характеристики: {str(e)}'
        }), 500
