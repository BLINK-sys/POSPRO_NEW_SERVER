from flask import Blueprint, request, jsonify
from extensions import db
from models.supplier import Supplier
from sqlalchemy import or_

suppliers_bp = Blueprint('suppliers', __name__)


@suppliers_bp.route('/', methods=['GET'])
def get_suppliers():
    """Получить все поставщики или выполнить поиск"""
    try:
        search_query = request.args.get('search', '').strip()
        
        if search_query:
            # Поиск по названию, контактному лицу, телефону, email
            suppliers = Supplier.query.filter(
                or_(
                    Supplier.name.ilike(f'%{search_query}%'),
                    Supplier.contact_person.ilike(f'%{search_query}%'),
                    Supplier.phone.ilike(f'%{search_query}%'),
                    Supplier.email.ilike(f'%{search_query}%'),
                    Supplier.address.ilike(f'%{search_query}%')
                )
            ).order_by(Supplier.name).all()
        else:
            # Получить все поставщики
            suppliers = Supplier.query.order_by(Supplier.name).all()
        
        return jsonify({
            'success': True,
            'data': [supplier.to_dict() for supplier in suppliers],
            'count': len(suppliers)
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении списка поставщиков: {str(e)}'
        }), 500


@suppliers_bp.route('/<int:supplier_id>', methods=['GET'])
def get_supplier(supplier_id):
    """Получить поставщика по ID"""
    try:
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            return jsonify({
                'success': False,
                'message': 'Поставщик не найден'
            }), 404
        
        return jsonify({
            'success': True,
            'data': supplier.to_dict()
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении поставщика: {str(e)}'
        }), 500


@suppliers_bp.route('/', methods=['POST'])
def create_supplier():
    """Создать нового поставщика"""
    try:
        data = request.get_json()
        
        if not data or 'name' not in data:
            return jsonify({
                'success': False,
                'message': 'Отсутствует обязательное поле name'
            }), 400
        
        name = data['name'].strip()
        if not name:
            return jsonify({
                'success': False,
                'message': 'name не может быть пустым'
            }), 400
        
        # Проверяем, не существует ли уже поставщик с таким именем
        existing = Supplier.query.filter_by(name=name).first()
        if existing:
            return jsonify({
                'success': False,
                'message': 'Поставщик с таким названием уже существует'
            }), 400
        
        supplier = Supplier(
            name=name,
            contact_person=data.get('contact_person', '').strip() if data.get('contact_person') else None,
            phone=data.get('phone', '').strip() if data.get('phone') else None,
            email=data.get('email', '').strip() if data.get('email') else None,
            address=data.get('address', '').strip() if data.get('address') else None,
            description=data.get('description', '').strip() if data.get('description') else None
        )
        
        db.session.add(supplier)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Поставщик успешно создан',
            'data': supplier.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании поставщика: {str(e)}'
        }), 500


@suppliers_bp.route('/<int:supplier_id>', methods=['PUT'])
def update_supplier(supplier_id):
    """Обновить поставщика"""
    try:
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            return jsonify({
                'success': False,
                'message': 'Поставщик не найден'
            }), 404
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'Отсутствуют данные для обновления'
            }), 400
        
        # Обновляем поля
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({
                    'success': False,
                    'message': 'name не может быть пустым'
                }), 400
            
            # Проверяем, не существует ли уже поставщик с таким именем (кроме текущего)
            existing = Supplier.query.filter(
                Supplier.name == name,
                Supplier.id != supplier_id
            ).first()
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'Поставщик с таким названием уже существует'
                }), 400
            
            supplier.name = name
        
        if 'contact_person' in data:
            supplier.contact_person = data['contact_person'].strip() if data.get('contact_person') else None
        
        if 'phone' in data:
            supplier.phone = data['phone'].strip() if data.get('phone') else None
        
        if 'email' in data:
            supplier.email = data['email'].strip() if data.get('email') else None
        
        if 'address' in data:
            supplier.address = data['address'].strip() if data.get('address') else None
        
        if 'description' in data:
            supplier.description = data['description'].strip() if data.get('description') else None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Поставщик успешно обновлен',
            'data': supplier.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении поставщика: {str(e)}'
        }), 500


@suppliers_bp.route('/<int:supplier_id>', methods=['DELETE'])
def delete_supplier(supplier_id):
    """Удалить поставщика"""
    try:
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            return jsonify({
                'success': False,
                'message': 'Поставщик не найден'
            }), 404
        
        db.session.delete(supplier)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Поставщик успешно удален'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении поставщика: {str(e)}'
        }), 500

