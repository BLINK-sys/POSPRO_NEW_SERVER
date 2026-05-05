from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
)
from werkzeug.security import check_password_hash
from extensions import db
from models.systemuser import SystemUser
from models.user import User
import datetime

auth_bp = Blueprint('auth', __name__)


# Время жизни токенов:
#  - access: короткий, обновляется в фоне фронтом — если кто-то умудрится
#    украсть его, окно атаки минимальное.
#  - refresh: длинный, лежит в httpOnly + secure cookie. Обновляет access
#    через POST /auth/refresh. После 30 дней простоя юзер логинится заново.
ACCESS_TOKEN_TTL = datetime.timedelta(minutes=30)
REFRESH_TOKEN_TTL = datetime.timedelta(days=30)


def _issue_token_pair(identity: str, role: str) -> dict:
    """Создаёт пару токенов с одинаковыми claims о роли. Используется
    в login и refresh endpoint'ах — единое место правды."""
    access = create_access_token(
        identity=identity,
        additional_claims={"role": role},
        expires_delta=ACCESS_TOKEN_TTL,
    )
    refresh = create_refresh_token(
        identity=identity,
        additional_claims={"role": role},
        expires_delta=REFRESH_TOKEN_TTL,
    )
    return {"token": access, "refresh_token": refresh}


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    
    # Логируем полученные данные для отладки
    print(f"Registration data received: {data}")

    organization_type = data.get('organizationType')
    email = data.get('email')
    phone = data.get('phone')
    delivery_address = data.get('deliveryAddress')
    password = data.get('password')

    print(f"Parsed data - organization_type: {organization_type}, email: {email}, phone: {phone}, delivery_address: {delivery_address}, password: {'***' if password else None}")

    if not all([organization_type, email, phone, delivery_address, password]):
        missing_fields = []
        if not organization_type: missing_fields.append('organizationType')
        if not email: missing_fields.append('email')
        if not phone: missing_fields.append('phone')
        if not delivery_address: missing_fields.append('deliveryAddress')
        if not password: missing_fields.append('password')
        
        error_msg = f'Недостаточно данных. Отсутствуют поля: {", ".join(missing_fields)}'
        print(f"Registration error: {error_msg}")
        return jsonify({'error': error_msg}), 400

    if SystemUser.query.filter_by(email=email).first() or User.query.filter_by(email=email).first():
        error_msg = 'Пользователь с таким email уже существует'
        print(f"Registration error: {error_msg}")
        return jsonify({'error': error_msg}), 400

    try:
        user = User(
            organization_type=organization_type,
            email=email,
            phone=phone,
            delivery_address=delivery_address,
        )

        if organization_type == 'individual':
            user.full_name = data.get('fullName')
            print(f"Individual user - full_name: {user.full_name}")
        elif organization_type == 'ip':
            user.iin = data.get('iin')
            user.ip_name = data.get('ipName')
            print(f"IP user - iin: {user.iin}, ip_name: {user.ip_name}")
        elif organization_type == 'too':
            user.bin = data.get('bin')
            user.too_name = data.get('tooName')
            print(f"TOO user - bin: {user.bin}, too_name: {user.too_name}")
        else:
            error_msg = 'Неверный тип организации'
            print(f"Registration error: {error_msg}")
            return jsonify({'error': error_msg}), 400

        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        print(f"User registered successfully with ID: {user.id}")
        return jsonify({'message': 'Пользователь зарегистрирован', 'id': user.id})
        
    except Exception as e:
        db.session.rollback()
        error_msg = f'Ошибка регистрации: {str(e)}'
        print(f"Registration error: {error_msg}")
        return jsonify({'error': error_msg}), 400


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = (data.get('email') or '').strip()
    password = data.get('password')

    if not email or not password:
        return jsonify({'error': 'Не указаны email или пароль'}), 400

    # Поиск без учёта регистра — иначе пользователь, вводящий email с другим регистром,
    # не сможет войти, даже если такой email есть в БД.
    email_lower = email.lower()

    # Попробовать найти среди админов
    admin = SystemUser.query.filter(db.func.lower(SystemUser.email) == email_lower).first()
    if admin and check_password_hash(admin.password_hash, password):
        tokens = _issue_token_pair(str(admin.id), "admin")
        return jsonify({
            **tokens,
            'user': {
                'id': admin.id,
                'email': admin.email,
                'name': admin.full_name,
                'phone': admin.phone,
                'role': 'admin'
            }
        })

    # Попробовать найти среди клиентов
    user = User.query.filter(db.func.lower(User.email) == email_lower).first()
    if user and check_password_hash(user.password_hash, password):
        name = user.full_name or user.ip_name or user.too_name
        tokens = _issue_token_pair(str(user.id), "client")
        return jsonify({
            **tokens,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': name,
                'phone': user.phone,
                'role': 'client',
                'is_wholesale': bool(user.is_wholesale)
            }
        })

    return jsonify({'error': 'Неверный email или пароль'}), 401


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """
    Обмен refresh-токена на новую пару (access + refresh — rotating).
    Защищён @jwt_required(refresh=True) — пускает только refresh-токены,
    обычным access-токенам сюда нельзя.

    Зачем rotating refresh: если refresh-токен утёк, владелец получит
    новую пару при следующем обращении, а старая (которая у злоумышленника)
    станет одноразовой по факту использования. Полная защита требует
    черного списка отозванных, но даже без него ротация — best practice.
    """
    identity = get_jwt_identity()
    claims = get_jwt() or {}
    role = claims.get('role', 'client')

    # Проверка что юзер всё ещё существует — иначе старый токен мог бы
    # давать доступ удалённому пользователю до истечения refresh.
    if role == 'admin':
        if not SystemUser.query.get(int(identity)):
            return jsonify({'error': 'Пользователь не найден'}), 401
    else:
        if not User.query.get(int(identity)):
            return jsonify({'error': 'Пользователь не найден'}), 401

    tokens = _issue_token_pair(str(identity), role)
    return jsonify(tokens), 200


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
            'role': 'client',
            'is_wholesale': bool(user.is_wholesale)
        })

    return jsonify({'error': 'Неизвестная роль'}), 400
