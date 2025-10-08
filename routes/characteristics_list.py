from flask import Blueprint, request, jsonify
from extensions import db
from models.characteristics_list import CharacteristicsList
from utils.jwt import token_required, admin_required

characteristics_list_bp = Blueprint('characteristics_list', __name__)

@characteristics_list_bp.route('/characteristics-list', methods=['GET'])
@token_required
def get_characteristics_list():
    """Получить список всех характеристик"""
    try:
        characteristics = CharacteristicsList.query.all()
        return jsonify({
            'success': True,
            'data': [char.to_dict() for char in characteristics]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении списка характеристик: {str(e)}'
        }), 500

@characteristics_list_bp.route('/characteristics-list/<int:characteristic_id>', methods=['GET'])
@token_required
def get_characteristic(characteristic_id):
    """Получить характеристику по ID"""
    try:
        characteristic = CharacteristicsList.query.get_or_404(characteristic_id)
        return jsonify({
            'success': True,
            'data': characteristic.to_dict()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении характеристики: {str(e)}'
        }), 500

@characteristics_list_bp.route('/characteristics-list', methods=['POST'])
@admin_required
def create_characteristic():
    """Создать новую характеристику (только для админов)"""
    try:
        data = request.get_json()
        
        if not data or 'characteristic_key' not in data:
            return jsonify({
                'success': False,
                'message': 'Необходимо указать characteristic_key'
            }), 400
        
        # Проверяем, не существует ли уже такая характеристика
        existing = CharacteristicsList.query.filter_by(
            characteristic_key=data['characteristic_key']
        ).first()
        
        if existing:
            return jsonify({
                'success': False,
                'message': 'Характеристика с таким ключом уже существует'
            }), 400
        
        characteristic = CharacteristicsList(
            characteristic_key=data['characteristic_key'],
            unit_of_measurement=data.get('unit_of_measurement')
        )
        
        db.session.add(characteristic)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика создана успешно',
            'data': characteristic.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании характеристики: {str(e)}'
        }), 500

@characteristics_list_bp.route('/characteristics-list/<int:characteristic_id>', methods=['PUT'])
@admin_required
def update_characteristic(characteristic_id):
    """Обновить характеристику (только для админов)"""
    try:
        characteristic = CharacteristicsList.query.get_or_404(characteristic_id)
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'Необходимо передать данные для обновления'
            }), 400
        
        # Обновляем поля
        if 'characteristic_key' in data:
            # Проверяем, не существует ли уже такая характеристика
            existing = CharacteristicsList.query.filter(
                CharacteristicsList.characteristic_key == data['characteristic_key'],
                CharacteristicsList.id != characteristic_id
            ).first()
            
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'Характеристика с таким ключом уже существует'
                }), 400
            
            characteristic.characteristic_key = data['characteristic_key']
        
        if 'unit_of_measurement' in data:
            characteristic.unit_of_measurement = data['unit_of_measurement']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика обновлена успешно',
            'data': characteristic.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении характеристики: {str(e)}'
        }), 500

@characteristics_list_bp.route('/characteristics-list/<int:characteristic_id>', methods=['DELETE'])
@admin_required
def delete_characteristic(characteristic_id):
    """Удалить характеристику (только для админов)"""
    try:
        characteristic = CharacteristicsList.query.get_or_404(characteristic_id)
        
        db.session.delete(characteristic)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Характеристика удалена успешно'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении характеристики: {str(e)}'
        }), 500
