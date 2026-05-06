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
        'is_owner': bool(u.is_owner),
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

    # Логируем полученные данные для отладки
    print(f"Create system user data: {data}")

    # Нормализуем email — храним в lowercase, чтобы избежать проблем с регистром при логине
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Email обязателен'}), 400
    data['email'] = email

    # Проверка email во всех таблицах (без учёта регистра). Сообщение
    # делаем максимально явным — где именно занят email — иначе менеджер
    # видит «Email уже используется» и не понимает где искать.
    existing_admin = SystemUser.query.filter(db.func.lower(SystemUser.email) == email).first()
    existing_client = User.query.filter(db.func.lower(User.email) == email).first()
    if existing_admin:
        return jsonify({
            'error': f'Системный пользователь с email «{email}» уже существует. '
                     f'Откройте его карточку для редактирования или используйте другой email.'
        }), 400
    if existing_client:
        return jsonify({
            'error': f'Email «{email}» уже зарегистрирован как клиент. '
                     f'Используйте другой email — один email не может принадлежать одновременно клиенту и системному пользователю.'
        }), 400

    # Безопасная обработка access данных
    access_data = data.get('access', {})
    if isinstance(access_data, str):
        # Если access приходит как строка, пытаемся распарсить как JSON
        try:
            import json
            access_data = json.loads(access_data)
        except (json.JSONDecodeError, TypeError):
            print(f"Warning: access data is string and cannot be parsed: {access_data}")
            access_data = {}
    elif not isinstance(access_data, dict):
        print(f"Warning: access data is not dict: {type(access_data)}")
        access_data = {}

    user = SystemUser(
        full_name=data['full_name'],
        email=data['email'],
        phone=data.get('phone'),
        access_orders=access_data.get('orders', False),
        access_catalog=access_data.get('catalog', False),
        access_clients=access_data.get('clients', False),
        access_users=access_data.get('users', False),
        access_settings=access_data.get('settings', False),
        access_dashboard=access_data.get('dashboard', False),
        access_brands=access_data.get('brands', False),
        access_statuses=access_data.get('statuses', False),
        access_pages=access_data.get('pages', False),

    )
    try:
        user.set_password(data['password'])
        db.session.add(user)
        db.session.commit()
        print(f"System user created successfully with ID: {user.id}")
        return jsonify({'message': 'User created', 'id': user.id}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error creating system user: {e}")
        return jsonify({'error': f'Ошибка создания пользователя: {str(e)}'}), 400


@system_users_bp.route('/system-users/<int:user_id>', methods=['PUT'])
def update_system_user(user_id):
    user = SystemUser.query.get_or_404(user_id)
    data = request.json

    # Защита owner-флага: его нельзя снять через обычное PUT — иначе случайным
    # запросом/багом UI можно «обнулить» главного админа. Поле в payload
    # игнорируется. Если когда-то понадобится передавать признак — заведём
    # отдельный endpoint с явной проверкой что инициатор тоже owner.
    if 'is_owner' in (data or {}) and user.is_owner and data.get('is_owner') is False:
        return jsonify({'error': 'Снятие is_owner через этот endpoint не разрешено'}), 403
    
    # Логируем полученные данные для отладки
    print(f"Update system user data: {data}")

    new_email = (data.get('email') or '').strip().lower()
    if new_email and new_email != (user.email or '').lower():
        # Меняем email — проверяем что он не занят кем-то другим, иначе
        # commit упадёт на UNIQUE constraint и юзер увидит непонятную ошибку.
        clash_admin = SystemUser.query.filter(
            db.func.lower(SystemUser.email) == new_email,
            SystemUser.id != user_id,
        ).first()
        clash_client = User.query.filter(db.func.lower(User.email) == new_email).first()
        if clash_admin:
            return jsonify({
                'error': f'Системный пользователь с email «{new_email}» уже существует.'
            }), 400
        if clash_client:
            return jsonify({
                'error': f'Email «{new_email}» уже зарегистрирован как клиент. Используйте другой email.'
            }), 400

    user.full_name = data['full_name']
    user.email = new_email or data['email']
    user.phone = data.get('phone')
    
    # Безопасная обработка access данных
    access_data = data.get('access', {})
    if isinstance(access_data, str):
        # Если access приходит как строка, пытаемся распарсить как JSON
        try:
            import json
            access_data = json.loads(access_data)
        except (json.JSONDecodeError, TypeError):
            print(f"Warning: access data is string and cannot be parsed: {access_data}")
            access_data = {}
    elif not isinstance(access_data, dict):
        print(f"Warning: access data is not dict: {type(access_data)}")
        access_data = {}
    
    user.access_orders = access_data.get('orders', False)
    user.access_catalog = access_data.get('catalog', False)
    user.access_clients = access_data.get('clients', False)
    user.access_users = access_data.get('users', False)
    user.access_settings = access_data.get('settings', False)
    user.access_dashboard = access_data.get('dashboard', False)
    user.access_brands = access_data.get('brands', False)
    user.access_statuses = access_data.get('statuses', False)
    user.access_pages = access_data.get('pages', False)

    try:
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        db.session.commit()
        print(f"System user updated successfully: {user.email}")
        return jsonify({'message': 'User updated'})
    except Exception as e:
        db.session.rollback()
        print(f"Error updating system user: {e}")
        return jsonify({'error': f'Ошибка обновления пользователя: {str(e)}'}), 400


@system_users_bp.route('/system-users/<int:user_id>', methods=['DELETE'])
def delete_system_user(user_id):
    user = SystemUser.query.get_or_404(user_id)
    # Owner неудаляем — это главный аккаунт системы. Если когда-то понадобится
    # «передать» owner-роль другому — снять флаг и поставить новому будет
    # отдельной операцией со своим UI (сейчас не реализовано).
    if user.is_owner:
        return jsonify({'error': 'Главного владельца системы нельзя удалить'}), 403
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted'})
