from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models import Order, OrderItem, Cart, Product, User, OrderStatus, OrderManager, SystemUser
from extensions import db
import datetime
import secrets
import string

orders_bp = Blueprint('orders', __name__)


def generate_order_number():
    """Генерировать уникальный номер заказа"""
    timestamp = datetime.datetime.now().strftime('%Y%m%d')
    random_part = ''.join(secrets.choice(string.digits) for _ in range(4))
    return f"ORD-{timestamp}-{random_part}"


@orders_bp.route('/orders', methods=['POST'])
@jwt_required()
def create_order():
    """Создать заказ из корзины"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        data = request.get_json() or {}
        
        # Получаем товары из корзины
        cart_items = Cart.query.filter_by(user_id=user_id).all()
        
        if not cart_items:
            return jsonify({
                'success': False,
                'message': 'Корзина пуста'
            }), 400

        # Проверяем доступность всех товаров
        for cart_item in cart_items:
            product = cart_item.product
            if not product.is_visible:
                return jsonify({
                    'success': False,
                    'message': f'Товар "{product.name}" недоступен для покупки'
                }), 400
                
            if product.quantity < cart_item.quantity:
                return jsonify({
                    'success': False,
                    'message': f'Недостаточно товара "{product.name}" на складе. Доступно: {product.quantity}'
                }), 400

        # Подсчитываем общую сумму
        subtotal = sum(item.product.price * item.quantity for item in cart_items)
        total_amount = subtotal  # В будущем можно добавить доставку, скидки и т.д.

        # Получаем информацию о пользователе
        user = User.query.get(user_id)

        # Получаем дефолтный статус "В ожидании" (первый в порядке сортировки)
        default_status = OrderStatus.query.filter_by(is_active=True).order_by(OrderStatus.order.asc()).first()
        if not default_status:
            return jsonify({
                'success': False,
                'message': 'Активные статусы не найдены в системе'
            }), 500

        # Создаем заказ
        order = Order(
            user_id=user_id,
            order_number=generate_order_number(),
            status_id=default_status.id,
            payment_status='unpaid',
            subtotal=subtotal,
            total_amount=total_amount,
            customer_name=data.get('customer_name', user.get_display_name() if user else ''),
            customer_phone=data.get('customer_phone', user.phone if user else ''),
            customer_email=data.get('customer_email', user.email if user else ''),
            delivery_address=data.get('delivery_address', ''),
            delivery_method=data.get('delivery_method', 'pickup'),
            payment_method=data.get('payment_method', 'cash'),
            customer_comment=data.get('customer_comment', '')
        )

        db.session.add(order)
        db.session.flush()  # Получаем ID заказа

        # Создаем элементы заказа
        for cart_item in cart_items:
            product = cart_item.product
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_price=product.price,
                product_article=product.article,
                quantity=cart_item.quantity,
                price_per_item=product.price,
                total_price=product.price * cart_item.quantity
            )
            db.session.add(order_item)

        # Очищаем корзину после создания заказа
        Cart.query.filter_by(user_id=user_id).delete()

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Заказ успешно создан',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании заказа: {str(e)}'
        }), 500


@orders_bp.route('/orders', methods=['GET'])
@jwt_required()
def get_orders():
    """Получить заказы пользователя"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        # Параметры для пагинации
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        # Параметр для фильтрации по типу заказов
        order_type = request.args.get('type', 'active')  # active, completed, all
        print(f"DEBUG: Запрос заказов с типом: {order_type}")  # Отладочная информация
        
        # Получаем заказы пользователя с фильтрацией по статусам
        if order_type == 'active':
            # Активные заказы (исключаем финальные статусы)
            orders_query = Order.query.filter_by(user_id=user_id).join(OrderStatus).filter(
                OrderStatus.is_final == False
            ).order_by(Order.created_at.desc())
        elif order_type == 'completed':
            # Завершенные заказы (только финальные статусы)
            orders_query = Order.query.filter_by(user_id=user_id).join(OrderStatus).filter(
                OrderStatus.is_final == True
            ).order_by(Order.created_at.desc())
        else:
            # Все заказы
            orders_query = Order.query.filter_by(user_id=user_id).order_by(Order.created_at.desc())
        
        orders_pagination = orders_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )

        orders_data = []
        for order in orders_pagination.items:
            order_dict = order.to_dict()
            # Загружаем информацию о менеджере, если она есть
            if hasattr(order, 'manager_assignment') and order.manager_assignment:
                order_dict['manager'] = order.manager_assignment.to_dict()
            orders_data.append(order_dict)
        
        print(f"DEBUG: Найдено заказов: {len(orders_data)}, статус фильтра: {order_type}")

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': orders_pagination.total,
                    'pages': orders_pagination.pages,
                    'has_next': orders_pagination.has_next,
                    'has_prev': orders_pagination.has_prev
                }
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении заказов: {str(e)}'
        }), 500


@orders_bp.route('/orders/<int:order_id>', methods=['GET'])
@jwt_required()
def get_order(order_id):
    """Получить конкретный заказ"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        # Находим заказ пользователя
        order = Order.query.filter_by(id=order_id, user_id=user_id).first()
        
        if not order:
            return jsonify({
                'success': False,
                'message': 'Заказ не найден'
            }), 404

        return jsonify({
            'success': True,
            'data': order.to_dict()
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении заказа: {str(e)}'
        }), 500


@orders_bp.route('/orders/<int:order_id>/cancel', methods=['PUT'])
@jwt_required()
def cancel_order(order_id):
    """Отменить заказ (только если статус pending)"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        # Находим заказ пользователя
        order = Order.query.filter_by(id=order_id, user_id=user_id).first()
        
        if not order:
            return jsonify({
                'success': False,
                'message': 'Заказ не найден'
            }), 404

        # Проверяем, что заказ не в финальном статусе
        if order.status_info and order.status_info.is_final:
            return jsonify({
                'success': False,
                'message': 'Заказ нельзя отменить, так как он уже завершен'
            }), 400

        # Получаем статус "Отменён" (финальный статус для отмены)
        cancelled_status = OrderStatus.query.filter_by(name='Отменён').first()
        if not cancelled_status:
            return jsonify({
                'success': False,
                'message': 'Статус "Отменён" не найден в системе'
            }), 500

        order.status_id = cancelled_status.id
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Заказ отменен',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при отмене заказа: {str(e)}'
        }), 500



# 🔹 Получить все заказы для админки
@orders_bp.route('/admin/orders', methods=['GET'])
@jwt_required()
def get_admin_orders():
    """Получить все заказы с данными клиентов для админки"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # Получаем заказы с информацией о пользователях и статусах
        orders_query = Order.query.join(User).join(OrderStatus).outerjoin(OrderManager)
        
        # Пагинация
        orders_paginated = orders_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )

        orders_data = []
        for order in orders_paginated.items:
            order_dict = order.to_dict()
            orders_data.append(order_dict)

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': orders_paginated.total,
                    'pages': orders_paginated.pages,
                    'has_next': orders_paginated.has_next,
                    'has_prev': orders_paginated.has_prev
                }
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении заказов: {str(e)}'
        }), 500


# 🔹 Назначить менеджера на заказ
@orders_bp.route('/admin/orders/<int:order_id>/assign-manager', methods=['POST'])
@jwt_required()
def assign_manager_to_order(order_id):
    """Назначить менеджера на заказ"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        manager_id = data.get('manager_id')

        if not manager_id:
            return jsonify({
                'success': False,
                'message': 'ID менеджера обязателен'
            }), 400

        order = Order.query.get_or_404(order_id)
        manager = SystemUser.query.get_or_404(manager_id)

        # Проверяем, есть ли уже назначенный менеджер
        existing_assignment = OrderManager.query.filter_by(order_id=order_id).first()
        
        if existing_assignment:
            # Обновляем существующее назначение
            existing_assignment.manager_id = manager_id
            existing_assignment.assigned_by = user_id
            existing_assignment.assigned_at = datetime.datetime.now()
        else:
            # Создаем новое назначение
            assignment = OrderManager(
                order_id=order_id,
                manager_id=manager_id,
                assigned_by=user_id
            )
            db.session.add(assignment)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Менеджер {manager.full_name} назначен на заказ {order.order_number}',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при назначении менеджера: {str(e)}'
        }), 500


# 🔹 Получить список менеджеров для назначения
@orders_bp.route('/admin/managers', methods=['GET'])
@jwt_required()
def get_managers():
    """Получить список всех менеджеров"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        managers = SystemUser.query.all()
        managers_data = []
        
        for manager in managers:
            managers_data.append({
                'id': manager.id,
                'full_name': manager.full_name,
                'email': manager.email,
                'phone': manager.phone
            })

        return jsonify({
            'success': True,
            'data': managers_data
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении списка менеджеров: {str(e)}'
        }), 500


# 🔹 Обновить статус заказа (для админки)
@orders_bp.route('/admin/orders/<int:order_id>/status', methods=['PUT'])
@jwt_required()
def update_admin_order_status(order_id):
    """Обновить статус заказа через админку"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        status_id = data.get('status_id')

        if not status_id:
            return jsonify({
                'success': False,
                'message': 'ID статуса обязателен'
            }), 400

        order = Order.query.get_or_404(order_id)
        status_obj = OrderStatus.query.get_or_404(status_id)

        old_status_id = order.status_id
        order.status_id = status_id
        order.updated_at = datetime.datetime.now()

        # Обновляем даты в зависимости от статуса
        now = datetime.datetime.now()
        if status_obj.name == 'Подтвержден' and not order.confirmed_at:
            order.confirmed_at = now
        elif status_obj.name == 'Отправлен' and not order.shipped_at:
            order.shipped_at = now
        elif status_obj.name == 'Доставлен' and not order.delivered_at:
            order.delivered_at = now

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Статус заказа изменен на "{status_obj.name}"',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении статуса: {str(e)}'
        }), 500


# 🔹 Обновить статус оплаты заказа
@orders_bp.route('/admin/orders/<int:order_id>/payment-status', methods=['PUT'])
@jwt_required()
def update_payment_status(order_id):
    """Обновить статус оплаты заказа"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        payment_status = data.get('payment_status')

        if not payment_status or payment_status not in ['unpaid', 'paid', 'refunded']:
            return jsonify({
                'success': False,
                'message': 'Некорректный статус оплаты'
            }), 400

        order = Order.query.get_or_404(order_id)
        order.payment_status = payment_status
        order.updated_at = datetime.datetime.now()

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Статус оплаты изменен на "{payment_status}"',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении статуса оплаты: {str(e)}'
        }), 500


# 🔹 Получить детали заказа для админки
@orders_bp.route('/admin/orders/<int:order_id>', methods=['GET'])
@jwt_required()
def get_admin_order_details(order_id):
    """Получить детали заказа для админки"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        order = Order.query.get_or_404(order_id)
        return jsonify({
            'success': True,
            'data': order.to_dict()
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении деталей заказа: {str(e)}'
        }), 500


# 🔹 Принять заказ текущим менеджером
@orders_bp.route('/admin/orders/<int:order_id>/accept', methods=['POST'])
@jwt_required()
def accept_order(order_id):
    """Принять заказ текущим менеджером"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        order = Order.query.get_or_404(order_id)
        manager = SystemUser.query.get_or_404(user_id)

        # Проверяем, есть ли уже назначенный менеджер
        existing_assignment = OrderManager.query.filter_by(order_id=order_id).first()
        
        if existing_assignment:
            # Обновляем существующее назначение
            existing_assignment.manager_id = user_id
            existing_assignment.assigned_by = user_id
            existing_assignment.assigned_at = datetime.datetime.now()
        else:
            # Создаем новое назначение
            assignment = OrderManager(
                order_id=order_id,
                manager_id=user_id,
                assigned_by=user_id
            )
            db.session.add(assignment)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Заказ {order.order_number} принят менеджером {manager.full_name}',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при принятии заказа: {str(e)}'
        }), 500


# 🔹 Передать заказ другому менеджеру
@orders_bp.route('/admin/orders/<int:order_id>/transfer', methods=['POST'])
@jwt_required()
def transfer_order(order_id):
    """Передать заказ другому менеджеру"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        data = request.get_json()
        new_manager_id = data.get('manager_id')

        if not new_manager_id:
            return jsonify({
                'success': False,
                'message': 'ID нового менеджера обязателен'
            }), 400

        order = Order.query.get_or_404(order_id)
        new_manager = SystemUser.query.get_or_404(new_manager_id)
        current_manager = SystemUser.query.get(user_id)

        # Проверяем, есть ли назначенный менеджер
        existing_assignment = OrderManager.query.filter_by(order_id=order_id).first()
        
        if existing_assignment:
            # Обновляем существующее назначение
            existing_assignment.manager_id = new_manager_id
            existing_assignment.assigned_by = user_id
            existing_assignment.assigned_at = datetime.datetime.now()
        else:
            # Создаем новое назначение
            assignment = OrderManager(
                order_id=order_id,
                manager_id=new_manager_id,
                assigned_by=user_id
            )
            db.session.add(assignment)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Заказ {order.order_number} передан менеджеру {new_manager.full_name}',
            'data': order.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при передаче заказа: {str(e)}'
        }), 500


# 🔹 Получить товары заказа из order_items
@orders_bp.route('/admin/orders/<int:order_id>/items', methods=['GET'])
@jwt_required()
def get_order_items(order_id):
    """Получить детальную информацию о товарах в заказе"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        # Проверяем существование заказа
        order = Order.query.get_or_404(order_id)
        
        # Получаем все товары заказа
        order_items = OrderItem.query.filter_by(order_id=order_id).all()
        
        items_data = []
        for item in order_items:
            items_data.append({
                'id': item.id,
                'order_id': item.order_id,
                'product_id': item.product_id,
                'product_name': item.product_name,
                'product_article': item.product_article,
                'quantity': item.quantity,
                'price_per_item': float(item.price_per_item) if item.price_per_item else 0,
                'total_price': float(item.total_price) if item.total_price else 0,
                'product_price_at_order': float(item.product_price) if item.product_price else 0,
                # Дополнительная информация о текущем товаре (если он все еще существует)
                'current_product': {
                    'id': item.product.id,
                    'name': item.product.name,
                    'slug': item.product.slug,
                    'current_price': float(item.product.price) if item.product else 0,
                    'image_url': item.product.get_main_image_url() if item.product else None,
                    'is_visible': item.product.is_visible if item.product else False
                } if item.product else None
            })

        return jsonify({
            'success': True,
            'data': {
                'order_id': order_id,
                'order_number': order.order_number,
                'items': items_data,
                'items_count': len(items_data),
                'total_amount': float(order.total_amount) if order.total_amount else 0,
                'subtotal': float(order.subtotal) if order.subtotal else 0
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении товаров заказа: {str(e)}'
        }), 500


# 🔹 Получить новые заказы (без назначенного менеджера)
@orders_bp.route('/admin/orders/new', methods=['GET'])
@jwt_required()
def get_new_orders():
    """Получить новые заказы без назначенного менеджера"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # Получаем заказы БЕЗ назначенного менеджера
        orders_query = Order.query.join(User).join(OrderStatus).outerjoin(OrderManager).filter(
            OrderManager.id.is_(None)  # Только заказы без менеджера
        ).order_by(Order.created_at.desc())
        
        # Пагинация
        orders_paginated = orders_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )

        orders_data = []
        for order in orders_paginated.items:
            order_dict = order.to_dict()
            orders_data.append(order_dict)

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': orders_paginated.total,
                    'pages': orders_paginated.pages,
                    'has_next': orders_paginated.has_next,
                    'has_prev': orders_paginated.has_prev
                }
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении новых заказов: {str(e)}'
        }), 500


# 🔹 Получить заказы текущего менеджера
@orders_bp.route('/admin/orders/my', methods=['GET'])
@jwt_required()
def get_my_orders():
    """Получить заказы текущего менеджера с фильтрацией"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_id = request.args.get('status_id', type=int)
        search_query = request.args.get('search', '')

        # Базовый запрос для заказов текущего менеджера (исключая финальные статусы)
        orders_query = Order.query.join(User).join(OrderStatus).join(OrderManager).filter(
            OrderManager.manager_id == user_id,  # Только заказы текущего менеджера
            OrderStatus.is_final == False  # Исключаем финальные статусы
        )
        
        # Фильтрация по статусу
        if status_id:
            orders_query = orders_query.filter(Order.status_id == status_id)
        
        # Поиск по клиенту (имя, email, телефон)
        if search_query:
            search_pattern = f'%{search_query}%'
            orders_query = orders_query.filter(
                db.or_(
                    Order.customer_name.ilike(search_pattern),
                    Order.customer_email.ilike(search_pattern),
                    Order.customer_phone.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    User.phone.ilike(search_pattern)
                )
            )
        
        orders_query = orders_query.order_by(Order.created_at.desc())
        
        # Пагинация
        orders_paginated = orders_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )

        orders_data = []
        for order in orders_paginated.items:
            order_dict = order.to_dict()
            orders_data.append(order_dict)

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': orders_paginated.total,
                    'pages': orders_paginated.pages,
                    'has_next': orders_paginated.has_next,
                    'has_prev': orders_paginated.has_prev
                }
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении моих заказов: {str(e)}'
        }), 500


# 🔹 Получить завершенные заказы текущего менеджера
@orders_bp.route('/admin/orders/completed', methods=['GET'])
@jwt_required()
def get_completed_orders():
    """Получить завершенные заказы текущего менеджера с фильтрацией"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только администраторам'
            }), 403

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_id = request.args.get('status_id', type=int)
        search_query = request.args.get('search', '')

        # Базовый запрос для завершенных заказов текущего менеджера
        orders_query = Order.query.join(User).join(OrderStatus).join(OrderManager).filter(
            OrderManager.manager_id == user_id,  # Только заказы текущего менеджера
            OrderStatus.is_final == True  # Только финальные статусы
        )
        
        # Фильтрация по статусу (среди финальных)
        if status_id:
            orders_query = orders_query.filter(Order.status_id == status_id)
        
        # Поиск по клиенту (имя, email, телефон)
        if search_query:
            search_pattern = f'%{search_query}%'
            orders_query = orders_query.filter(
                db.or_(
                    Order.customer_name.ilike(search_pattern),
                    Order.customer_email.ilike(search_pattern),
                    Order.customer_phone.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    User.phone.ilike(search_pattern)
                )
            )
        
        orders_query = orders_query.order_by(Order.created_at.desc())
        
        # Пагинация
        orders_paginated = orders_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )

        orders_data = []
        for order in orders_paginated.items:
            order_dict = order.to_dict()
            orders_data.append(order_dict)

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': orders_paginated.total,
                    'pages': orders_paginated.pages,
                    'has_next': orders_paginated.has_next,
                    'has_prev': orders_paginated.has_prev
                }
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении завершенных заказов: {str(e)}'
        }), 500
