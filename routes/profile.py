from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.systemuser import SystemUser
from models.user import User
from extensions import db
from werkzeug.security import generate_password_hash

profile_bp = Blueprint('profile', __name__)


# 🔹 Получить профиль текущего пользователя (админа или клиента)
@profile_bp.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    user_id = get_jwt_identity()
    jwt_data = get_jwt()
    role = jwt_data.get('role')

    if role == 'admin':
        user = SystemUser.query.get(user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        return jsonify({
            'id': user.id,
            'role': 'admin',
            'fullName': user.full_name,
            'email': user.email,
            'phone': user.phone,
            'access': {
                'orders': user.access_orders,
                'catalog': user.access_catalog,
                'clients': user.access_clients,
                'users': user.access_users,
                'settings': user.access_settings,
                'dashboard': user.access_dashboard,
                'brands': user.access_brands,
                'statuses': user.access_statuses,
                'pages': user.access_pages
            }

        })

    elif role == 'client':
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'Клиент не найден'}), 404

        profile = {
            'id': user.id,
            'role': 'client',
            'organizationType': user.organization_type,
            'email': user.email,
            'phone': user.phone,
            'deliveryAddress': user.delivery_address,
        }

        if user.organization_type == 'individual':
            profile['fullName'] = user.full_name
        elif user.organization_type == 'ip':
            profile['ipName'] = user.ip_name
            profile['iin'] = user.iin
        elif user.organization_type == 'too':
            profile['tooName'] = user.too_name
            profile['bin'] = user.bin

        return jsonify(profile)

    return jsonify({'error': 'Неизвестная роль'}), 400


# 🔹 Обновить профиль текущего пользователя
@profile_bp.route('/api/profile', methods=['PATCH'])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()
    jwt_data = get_jwt()
    role = jwt_data.get('role')
    data = request.get_json()

    if role == 'admin':
        user = SystemUser.query.get(user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        user.full_name = data.get('fullName', user.full_name)
        user.phone = data.get('phone', user.phone)

        if data.get('password'):
            user.password_hash = generate_password_hash(data['password'])

        db.session.commit()
        return jsonify({'message': 'Профиль обновлён'})

    elif role == 'client':
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'Клиент не найден'}), 404

        user.phone = data.get('phone', user.phone)
        user.delivery_address = data.get('deliveryAddress', user.delivery_address)

        if user.organization_type == 'individual':
            user.full_name = data.get('fullName', user.full_name)
        elif user.organization_type == 'ip':
            user.ip_name = data.get('ipName', user.ip_name)
            user.iin = data.get('iin', user.iin)
        elif user.organization_type == 'too':
            user.too_name = data.get('tooName', user.too_name)
            user.bin = data.get('bin', user.bin)

        if data.get('password'):
            user.password_hash = generate_password_hash(data['password'])

        db.session.commit()
        return jsonify({'message': 'Профиль обновлён'})

    return jsonify({'error': 'Неизвестная роль'}), 400


# 🔹 Получить адрес доставки текущего клиента
@profile_bp.route('/api/profile/delivery-address', methods=['GET'])
@jwt_required()
def get_delivery_address():
    user_id = get_jwt_identity()
    jwt_data = get_jwt()
    role = jwt_data.get('role')

    if role != 'client':
        return jsonify({'error': 'Доступ разрешен только клиентам'}), 403

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Клиент не найден'}), 404

    return jsonify({
        'success': True,
        'data': {
            'delivery_address': user.delivery_address or ''
        }
    })