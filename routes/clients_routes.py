from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from extensions import db
from models.systemuser import SystemUser
from models.user import User

clients_bp = Blueprint('clients', __name__)


# 🔹 Получить список клиентов
@clients_bp.route('/api/clients', methods=['GET'])
def get_clients():
    clients = User.query.all()
    result = []

    for user in clients:
        name = ''
        identifier = ''
        if user.organization_type == 'individual':
            name = user.full_name or ''
        elif user.organization_type == 'ip':
            name = user.ip_name or ''
            identifier = user.iin or ''
        elif user.organization_type == 'too':
            name = user.too_name or ''
            identifier = user.bin or ''

        result.append({
            'id': user.id,
            'type': user.organization_type,
            'identifier': identifier,
            'name': name,
            'email': user.email,
            'phone': user.phone,
            'delivery_address': user.delivery_address
        })

    return jsonify(result)


# 🔹 Создать клиента
@clients_bp.route('/api/clients', methods=['POST'])
def create_client():
    data = request.get_json()

    # Проверка email во всех таблицах
    existing_client = User.query.filter_by(email=data['email']).first()
    existing_admin = SystemUser.query.filter_by(email=data['email']).first()
    if existing_client or existing_admin:
        return jsonify({'error': 'Email уже зарегистрирован'}), 400

    user = User(
        organization_type=data['organization_type'],
        email=data['email'],
        phone=data['phone'],
        delivery_address=data['delivery_address'],
        password_hash=generate_password_hash(data['password'])
    )

    if user.organization_type == 'individual':
        user.full_name = data.get('full_name')
    elif user.organization_type == 'ip':
        user.iin = data.get('iin')
        user.ip_name = data.get('ip_name')
    elif user.organization_type == 'too':
        user.bin = data.get('bin')
        user.too_name = data.get('too_name')

    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Клиент создан', 'id': user.id}), 201


# 🔹 Получить одного клиента по ID
@clients_bp.route('/api/clients/<int:user_id>', methods=['GET'])
def get_client(user_id):
    user = User.query.get_or_404(user_id)
    
    profile = {
        'id': user.id,
        'type': user.organization_type,
        'email': user.email,
        'phone': user.phone,
        'delivery_address': user.delivery_address,
    }

    if user.organization_type == 'individual':
        profile['full_name'] = user.full_name
    elif user.organization_type == 'ip':
        profile['ip_name'] = user.ip_name
        profile['iin'] = user.iin
    elif user.organization_type == 'too':
        profile['too_name'] = user.too_name
        profile['bin'] = user.bin

    return jsonify(profile)


# 🔹 Обновить клиента
@clients_bp.route('/api/clients/<int:user_id>', methods=['PUT'])
def update_client(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()

    user.organization_type = data.get('organization_type', user.organization_type)
    user.email = data.get('email', user.email)
    user.phone = data.get('phone', user.phone)
    user.delivery_address = data.get('delivery_address', user.delivery_address)

    if user.organization_type == 'individual':
        user.full_name = data.get('full_name', user.full_name)
        user.iin = None
        user.ip_name = None
        user.bin = None
        user.too_name = None
    elif user.organization_type == 'ip':
        user.iin = data.get('iin', user.iin)
        user.ip_name = data.get('ip_name', user.ip_name)
        user.full_name = None
        user.bin = None
        user.too_name = None
    elif user.organization_type == 'too':
        user.bin = data.get('bin', user.bin)
        user.too_name = data.get('too_name', user.too_name)
        user.full_name = None
        user.iin = None
        user.ip_name = None

    if 'password' in data and data['password']:
        user.password_hash = generate_password_hash(data['password'])

    db.session.commit()
    return jsonify({'message': 'Клиент обновлён'})


# 🔹 Удалить клиента
@clients_bp.route('/api/clients/<int:user_id>', methods=['DELETE'])
def delete_client(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'Клиент удалён'})
