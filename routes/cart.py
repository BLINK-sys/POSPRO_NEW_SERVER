from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models import Cart, Product, User
from extensions import db

cart_bp = Blueprint('cart', __name__)


@cart_bp.route('/cart', methods=['GET'])
@jwt_required()
def get_cart():
    """Получить корзину пользователя"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        cart_items = Cart.query.filter_by(user_id=user_id).all()

        # Проверяем оптовый статус пользователя
        user = User.query.get(user_id)
        is_wholesale = bool(user.is_wholesale) if user else False

        # Подсчитываем общую сумму
        total_amount = 0
        items_data = []

        for item in cart_items:
            item_data = item.to_dict(is_wholesale=is_wholesale)
            items_data.append(item_data)
            total_amount += item_data['total_price']

        return jsonify({
            'success': True,
            'data': {
                'items': items_data,
                'total_amount': total_amount,
                'items_count': len(items_data)
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении корзины: {str(e)}'
        }), 500


@cart_bp.route('/cart', methods=['POST'])
@jwt_required()
def add_to_cart():
    """Добавить товар в корзину"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        data = request.get_json()
        product_id = data.get('product_id')
        quantity = data.get('quantity', 1)

        if not product_id:
            return jsonify({
                'success': False,
                'message': 'Не указан ID товара'
            }), 400

        if quantity < 1:
            return jsonify({
                'success': False,
                'message': 'Количество должно быть больше 0'
            }), 400

        # Проверяем существование товара
        product = Product.query.get(product_id)
        if not product:
            return jsonify({
                'success': False,
                'message': 'Товар не найден'
            }), 404

        # Проверяем доступность товара
        if not product.is_visible:
            return jsonify({
                'success': False,
                'message': 'Товар недоступен для покупки'
            }), 400

        # Проверяем наличие товара на складе
        if product.quantity < quantity:
            return jsonify({
                'success': False,
                'message': f'Недостаточно товара на складе. Доступно: {product.quantity}'
            }), 400

        # Проверяем, есть ли уже этот товар в корзине
        existing_item = Cart.query.filter_by(user_id=user_id, product_id=product_id).first()
        
        if existing_item:
            # Обновляем количество
            new_quantity = existing_item.quantity + quantity
            
            # Проверяем общее количество
            if product.quantity < new_quantity:
                return jsonify({
                    'success': False,
                    'message': f'Недостаточно товара на складе. Доступно: {product.quantity}, в корзине: {existing_item.quantity}'
                }), 400
            
            existing_item.quantity = new_quantity
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Количество товара в корзине обновлено',
                'data': existing_item.to_dict()
            })
        else:
            # Создаем новую запись в корзине
            cart_item = Cart(
                user_id=user_id,
                product_id=product_id,
                quantity=quantity
            )
            
            db.session.add(cart_item)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Товар добавлен в корзину',
                'data': cart_item.to_dict()
            })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при добавлении товара в корзину: {str(e)}'
        }), 500


@cart_bp.route('/cart/<int:item_id>', methods=['PUT'])
@jwt_required()
def update_cart_item(item_id):
    """Обновить количество товара в корзине"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        data = request.get_json()
        quantity = data.get('quantity')

        if quantity is None or quantity < 1:
            return jsonify({
                'success': False,
                'message': 'Количество должно быть больше 0'
            }), 400

        # Найти товар в корзине пользователя
        cart_item = Cart.query.filter_by(id=item_id, user_id=user_id).first()
        if not cart_item:
            return jsonify({
                'success': False,
                'message': 'Товар не найден в корзине'
            }), 404

        # Проверяем доступность товара на складе
        if cart_item.product.quantity < quantity:
            return jsonify({
                'success': False,
                'message': f'Недостаточно товара на складе. Доступно: {cart_item.product.quantity}'
            }), 400

        cart_item.quantity = quantity
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Количество товара обновлено',
            'data': cart_item.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при обновлении товара: {str(e)}'
        }), 500


@cart_bp.route('/cart/<int:item_id>', methods=['DELETE'])
@jwt_required()
def remove_from_cart(item_id):
    """Удалить товар из корзины"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        # Найти товар в корзине пользователя
        cart_item = Cart.query.filter_by(id=item_id, user_id=user_id).first()
        if not cart_item:
            return jsonify({
                'success': False,
                'message': 'Товар не найден в корзине'
            }), 404

        db.session.delete(cart_item)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Товар удален из корзины'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении товара: {str(e)}'
        }), 500


@cart_bp.route('/cart/clear', methods=['DELETE'])
@jwt_required()
def clear_cart():
    """Очистить корзину"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        Cart.query.filter_by(user_id=user_id).delete()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Корзина очищена'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при очистке корзины: {str(e)}'
        }), 500


@cart_bp.route('/cart/count', methods=['GET'])
@jwt_required()
def get_cart_count():
    """Получить количество товаров в корзине"""
    try:
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403

        count = Cart.query.filter_by(user_id=user_id).count()

        return jsonify({
            'success': True,
            'data': {
                'count': count
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении количества товаров: {str(e)}'
        }), 500
