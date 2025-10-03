from flask import Blueprint, request, jsonify
from extensions import db
from models.systemuser import SystemUser
from models.user import User

system_users_bp = Blueprint('system_users', __name__)


@system_users_bp.route('/system-users', methods=['GET'])
def get_system_users():
    users = SystemUser.query.all()
    return jsonify([{
        'id': u.id,
        'full_name': u.full_name,
        'email': u.email,
        'phone': u.phone,
        'access': {
            'orders': u.access_orders,
            'catalog': u.access_catalog,
            'clients': u.access_clients,
            'users': u.access_users,
            'settings': u.access_settings,
            'dashboard': u.access_dashboard,
            'brands': u.access_brands,
            'statuses': u.access_statuses,
            'pages': u.access_pages
        }

    } for u in users])


@system_users_bp.route('/system-users', methods=['POST'])
def create_system_user():
    data = request.get_json()

    # Проверка email во всех таблицах
    existing_admin = SystemUser.query.filter_by(email=data['email']).first()
    existing_client = User.query.filter_by(email=data['email']).first()
    if existing_admin or existing_client:
        return jsonify({'error': 'Email уже используется'}), 400


    user = SystemUser(
        full_name=data['full_name'],
        email=data['email'],
        phone=data.get('phone'),
        access_orders=data.get('access', {}).get('orders', False),
        access_catalog=data.get('access', {}).get('catalog', False),
        access_clients=data.get('access', {}).get('clients', False),
        access_users=data.get('access', {}).get('users', False),
        access_settings=data.get('access', {}).get('settings', False),
        access_dashboard=data.get('access', {}).get('dashboard', False),
        access_brands=data.get('access', {}).get('brands', False),
        access_statuses=data.get('access', {}).get('statuses', False),
        access_pages=data.get('access', {}).get('pages', False),

    )
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'User created', 'id': user.id}), 201


@system_users_bp.route('/system-users/<int:user_id>', methods=['PUT'])
def update_system_user(user_id):
    user = SystemUser.query.get_or_404(user_id)
    data = request.json
    user.full_name = data['full_name']
    user.email = data['email']
    user.phone = data.get('phone')
    user.access_orders = data.get('access', {}).get('orders', False)
    user.access_catalog = data.get('access', {}).get('catalog', False)
    user.access_clients = data.get('access', {}).get('clients', False)
    user.access_users = data.get('access', {}).get('users', False)
    user.access_settings = data.get('access', {}).get('settings', False)
    user.access_dashboard = data.get('access', {}).get('dashboard', False)
    user.access_brands = data.get('access', {}).get('brands', False)
    user.access_statuses = data.get('access', {}).get('statuses', False)
    user.access_pages = data.get('access', {}).get('pages', False)

    if 'password' in data and data['password']:
        user.set_password(data['password'])
    db.session.commit()
    return jsonify({'message': 'User updated'})


@system_users_bp.route('/system-users/<int:user_id>', methods=['DELETE'])
def delete_system_user(user_id):
    user = SystemUser.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted'})
