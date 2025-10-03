from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from models.favorite import Favorite
from models.product import Product
from models.user import User
from extensions import db
from sqlalchemy.exc import IntegrityError

favorites_bp = Blueprint('favorites', __name__)


@favorites_bp.route('/favorites', methods=['GET'])
@jwt_required()
def get_user_favorites():
    """Получить список избранных товаров пользователя"""
    try:
        # Получаем ID пользователя и проверяем роль
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')
        
        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403
            
        favorites = Favorite.query.filter_by(user_id=user_id).all()
        
        favorites_data = []
        for favorite in favorites:
            if favorite.product:  # Проверяем, что товар существует
                favorites_data.append(favorite.to_dict())
        
        return jsonify({
            'success': True,
            'favorites': favorites_data,
            'count': len(favorites_data)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при получении избранного: {str(e)}'
        }), 500


@favorites_bp.route('/favorites', methods=['POST'])
@jwt_required()
def add_to_favorites():
    """Добавить товар в избранное"""
    try:
        # Получаем ID пользователя и проверяем роль
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
        
        if not product_id:
            return jsonify({
                'success': False,
                'message': 'ID товара обязателен'
            }), 400
            
        # Проверяем, существует ли товар
        product = Product.query.get(product_id)
        if not product:
            return jsonify({
                'success': False,
                'message': 'Товар не найден'
            }), 404
            
        # Проверяем, не добавлен ли уже товар в избранное
        existing_favorite = Favorite.query.filter_by(
            user_id=user_id,
            product_id=product_id
        ).first()
        
        if existing_favorite:
            return jsonify({
                'success': False,
                'message': 'Товар уже в избранном'
            }), 409
            
        # Создаем новое избранное
        favorite = Favorite(
            user_id=user_id,
            product_id=product_id
        )
        
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Товар добавлен в избранное',
            'favorite': favorite.to_dict()
        }), 201
        
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Товар уже в избранном'
        }), 409
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при добавлении в избранное: {str(e)}'
        }), 500


@favorites_bp.route('/favorites/<int:product_id>', methods=['DELETE'])
@jwt_required()
def remove_from_favorites(product_id):
    """Удалить товар из избранного"""
    try:
        # Получаем ID пользователя и проверяем роль
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')
        
        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403
            
        favorite = Favorite.query.filter_by(
            user_id=user_id,
            product_id=product_id
        ).first()
        
        if not favorite:
            return jsonify({
                'success': False,
                'message': 'Товар не найден в избранном'
            }), 404
            
        db.session.delete(favorite)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Товар удален из избранного'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при удалении из избранного: {str(e)}'
        }), 500


@favorites_bp.route('/favorites/check/<int:product_id>', methods=['GET'])
@jwt_required()
def check_favorite_status(product_id):
    """Проверить, находится ли товар в избранном у пользователя"""
    try:
        # Получаем ID пользователя и проверяем роль
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')
        
        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403
            
        favorite = Favorite.query.filter_by(
            user_id=user_id,
            product_id=product_id
        ).first()
        
        return jsonify({
            'success': True,
            'is_favorite': favorite is not None
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при проверке статуса избранного: {str(e)}'
        }), 500


@favorites_bp.route('/favorites/toggle', methods=['POST'])
@jwt_required()
def toggle_favorite():
    """Переключить статус избранного (добавить/удалить)"""
    try:
        # Получаем ID пользователя и проверяем роль
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
        
        if not product_id:
            return jsonify({
                'success': False,
                'message': 'ID товара обязателен'
            }), 400
            
        # Проверяем, существует ли товар
        product = Product.query.get(product_id)
        if not product:
            return jsonify({
                'success': False,
                'message': 'Товар не найден'
            }), 404
            
        # Проверяем текущий статус
        existing_favorite = Favorite.query.filter_by(
            user_id=user_id,
            product_id=product_id
        ).first()
        
        if existing_favorite:
            # Удаляем из избранного
            db.session.delete(existing_favorite)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Товар удален из избранного',
                'is_favorite': False
            }), 200
        else:
            # Добавляем в избранное
            favorite = Favorite(
                user_id=user_id,
                product_id=product_id
            )
            
            db.session.add(favorite)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Товар добавлен в избранное',
                'is_favorite': True,
                'favorite': favorite.to_dict()
            }), 201
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Ошибка при переключении избранного: {str(e)}'
        }), 500
