from flask import Blueprint, jsonify
from models.product_availability_status import ProductAvailabilityStatus

public_product_availability_statuses_bp = Blueprint('public_product_availability_statuses', __name__)


# 🔹 Получить статус для товара по количеству (публичный эндпоинт)
@public_product_availability_statuses_bp.route('/product-availability-statuses/check/<int:quantity>', methods=['GET'])
def get_status_for_quantity(quantity):
    try:
        # Получаем активные статусы, отсортированные по порядку
        statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()
        
        # Находим подходящий статус
        for status in statuses:
            if status.check_condition(quantity):
                return jsonify({
                    'status': status.to_dict(),
                    'formula': status.get_formula_display()
                })
        
        # Если не найден подходящий статус, возвращаем null
        return jsonify({'status': None, 'formula': None})
        
    except Exception as e:
        return jsonify({'error': f'Ошибка получения статуса: {str(e)}'}), 500

