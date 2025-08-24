# jwt.py
# Этот файл больше не используется в новой реализации избранного
# Все маршруты избранного теперь используют flask_jwt_extended напрямую

from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt


def token_required(f):
    """
    DEPRECATED: Используйте @jwt_required() из flask_jwt_extended вместо этого декоратора
    """
    @wraps(f)
    @jwt_required()
    def decorated(*args, **kwargs):
        user_id = get_jwt_identity()
        jwt_data = get_jwt()
        role = jwt_data.get('role')
        
        if role != 'client':
            return jsonify({
                'success': False,
                'message': 'Доступ разрешен только клиентам'
            }), 403
            
        return f(user_id, *args, **kwargs)
    
    return decorated
