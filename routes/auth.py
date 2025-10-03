from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import check_password_hash
from extensions import db
from models.systemuser import SystemUser
from models.user import User
import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json or {}

    organization_type = data.get('organizationType')
    email = data.get('email')
    phone = data.get('phone')
    delivery_address = data.get('deliveryAddress')
    password = data.get('password')

    if not all([organization_type, email, phone, delivery_address, password]):
        return jsonify({'error': 'Недостаточно данных'}), 400

    if SystemUser.query.filter_by(email=email).first() or User.query.filter_by(email=email).first():
        return jsonify({'error': 'Пользователь с таким email уже существует'}), 400

    user = User(
        organization_type=organization_type,
        email=email,
        phone=phone,
        delivery_address=delivery_address,
    )

    if organization_type == 'individual':
        user.full_name = data.get('fullName')
    elif organization_type == 'ip':
        user.iin = data.get('iin')
        user.ip_name = data.get('ipName')
    elif organization_type == 'too':
        user.bin = data.get('bin')
        user.too_name = data.get('tooName')
    else:
        return jsonify({'error': 'Неверный тип организации'}), 400

    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'Пользователь зарегистрирован', 'id': user.id})


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    # Попробовать найти среди админов
    admin = SystemUser.query.filter_by(email=email).first()
    if admin and check_password_hash(admin.password_hash, password):
        token = create_access_token(
            identity=str(admin.id),
            additional_claims={"role": "admin"},
            expires_delta=datetime.timedelta(hours=3)
        )

        return jsonify({
            'token': token,
            'user': {
                'id': admin.id,
                'email': admin.email,
                'name': admin.full_name,
                'phone': admin.phone,
                'role': 'admin'
            }
        })

    # Попробовать найти среди клиентов
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password_hash, password):
        name = user.full_name or user.ip_name or user.too_name

        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": "client"},
            expires_delta=datetime.timedelta(hours=3)
        )

        return jsonify({
            'token': token,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': name,
                'phone': user.phone,
                'role': 'client'
            }
        })

    return jsonify({'error': 'Неверный email или пароль'}), 401


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    jwt_data = get_jwt()
    user_id = get_jwt_identity()
    role = jwt_data.get('role')

    if role == 'admin':
        user = SystemUser.query.get(user_id)
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404

        return jsonify({
            'id': user.id,
            'email': user.email,
            'name': user.full_name,
            'phone': user.phone,
            'role': 'admin'
        })

    elif role == 'client':
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'Клиент не найден'}), 404

        name = user.full_name or user.ip_name or user.too_name
        return jsonify({
            'id': user.id,
            'email': user.email,
            'name': name,
            'phone': user.phone,
            'role': 'client'
        })

    return jsonify({'error': 'Неизвестная роль'}), 400
