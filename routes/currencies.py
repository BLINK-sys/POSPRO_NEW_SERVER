from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.currency import Currency

currencies_bp = Blueprint('currencies', __name__)


def check_admin():
    jwt_data = get_jwt()
    role = jwt_data.get('role')
    if role not in ('admin', 'system'):
        return False
    return True


@currencies_bp.route('/', methods=['GET'])
@jwt_required()
def get_currencies():
    currencies = Currency.query.order_by(Currency.name).all()
    return jsonify({
        'success': True,
        'data': [c.to_dict() for c in currencies],
        'count': len(currencies)
    }), 200


@currencies_bp.route('/<int:currency_id>', methods=['GET'])
@jwt_required()
def get_currency(currency_id):
    currency = Currency.query.get(currency_id)
    if not currency:
        return jsonify({'success': False, 'message': 'Валюта не найдена'}), 404
    return jsonify({'success': True, 'data': currency.to_dict()}), 200


@currencies_bp.route('/', methods=['POST'])
@jwt_required()
def create_currency():
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    data = request.get_json()
    if not data or 'name' not in data or 'code' not in data:
        return jsonify({'success': False, 'message': 'Обязательные поля: name, code'}), 400

    name = data['name'].strip()
    code = data['code'].strip().upper()
    rate_to_tenge = data.get('rate_to_tenge', 1.0)

    existing = Currency.query.filter_by(code=code).first()
    if existing:
        return jsonify({'success': False, 'message': f'Валюта с кодом {code} уже существует'}), 400

    currency = Currency(
        name=name,
        code=code,
        rate_to_tenge=float(rate_to_tenge)
    )
    db.session.add(currency)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Валюта создана',
        'data': currency.to_dict()
    }), 201


@currencies_bp.route('/<int:currency_id>', methods=['PUT'])
@jwt_required()
def update_currency(currency_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    currency = Currency.query.get(currency_id)
    if not currency:
        return jsonify({'success': False, 'message': 'Валюта не найдена'}), 404

    data = request.get_json()

    if 'name' in data:
        currency.name = data['name'].strip()
    if 'code' in data:
        new_code = data['code'].strip().upper()
        existing = Currency.query.filter(
            Currency.code == new_code,
            Currency.id != currency_id
        ).first()
        if existing:
            return jsonify({'success': False, 'message': f'Валюта с кодом {new_code} уже существует'}), 400
        currency.code = new_code
    if 'rate_to_tenge' in data:
        currency.rate_to_tenge = float(data['rate_to_tenge'])

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Валюта обновлена',
        'data': currency.to_dict()
    }), 200


@currencies_bp.route('/<int:currency_id>', methods=['DELETE'])
@jwt_required()
def delete_currency(currency_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    currency = Currency.query.get(currency_id)
    if not currency:
        return jsonify({'success': False, 'message': 'Валюта не найдена'}), 404

    # Check if any warehouses use this currency
    from models.warehouse import Warehouse
    warehouse_count = Warehouse.query.filter_by(currency_id=currency_id).count()
    if warehouse_count > 0:
        return jsonify({
            'success': False,
            'message': f'Невозможно удалить: валюта используется в {warehouse_count} складах'
        }), 400

    db.session.delete(currency)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Валюта удалена'}), 200
