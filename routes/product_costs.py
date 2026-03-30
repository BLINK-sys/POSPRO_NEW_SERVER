from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.product_warehouse_cost import ProductWarehouseCost
from models.warehouse import Warehouse, WarehouseVariable, WarehouseFormula
from models.product import Product
from models.media import ProductMedia
from utils.formula_engine import (
    calculate_product_price, extract_product_characteristics, FormulaError
)
from datetime import datetime

product_costs_bp = Blueprint('product_costs', __name__)


def check_admin():
    jwt_data = get_jwt()
    role = jwt_data.get('role')
    if role not in ('admin', 'system'):
        return False
    return True


@product_costs_bp.route('/', methods=['GET'])
@jwt_required()
def get_product_costs():
    warehouse_id = request.args.get('warehouse_id', type=int)
    product_id = request.args.get('product_id', type=int)

    query = ProductWarehouseCost.query

    if warehouse_id:
        query = query.filter_by(warehouse_id=warehouse_id)
    if product_id:
        query = query.filter_by(product_id=product_id)

    costs = query.all()

    result = []
    for c in costs:
        data = c.to_dict()
        # Add product image
        image = ProductMedia.query.filter_by(
            product_id=c.product_id, media_type='image'
        ).order_by(ProductMedia.order).first()
        data['product_image'] = image.url if image else None
        # Add warehouse and supplier names
        warehouse = Warehouse.query.get(c.warehouse_id)
        if warehouse:
            data['warehouse_name'] = warehouse.name
            data['supplier_name'] = warehouse.supplier.name if warehouse.supplier else None
        else:
            data['warehouse_name'] = None
            data['supplier_name'] = None
        result.append(data)

    return jsonify({
        'success': True,
        'data': result,
        'count': len(result)
    }), 200


@product_costs_bp.route('/count', methods=['GET'])
@jwt_required()
def get_product_costs_count():
    warehouse_id = request.args.get('warehouse_id', type=int)
    product_id = request.args.get('product_id', type=int)

    query = ProductWarehouseCost.query

    if warehouse_id:
        query = query.filter_by(warehouse_id=warehouse_id)
    if product_id:
        query = query.filter_by(product_id=product_id)

    count = query.count()

    return jsonify({
        'success': True,
        'count': count
    }), 200


@product_costs_bp.route('/', methods=['POST'])
@jwt_required()
def create_product_cost():
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    data = request.get_json()

    product_id = data.get('product_id')
    warehouse_id = data.get('warehouse_id')
    cost_price = data.get('cost_price')

    if not product_id or not warehouse_id or cost_price is None:
        return jsonify({
            'success': False,
            'message': 'Обязательные поля: product_id, warehouse_id, cost_price'
        }), 400

    # Check for duplicates
    existing = ProductWarehouseCost.query.filter_by(
        product_id=product_id,
        warehouse_id=warehouse_id
    ).first()
    if existing:
        return jsonify({
            'success': False,
            'message': 'Себестоимость для этого товара на этом складе уже задана'
        }), 400

    pwc = ProductWarehouseCost(
        product_id=product_id,
        warehouse_id=warehouse_id,
        cost_price=float(cost_price)
    )

    # Try to calculate price immediately
    _try_calculate(pwc)

    db.session.add(pwc)
    db.session.commit()

    # Update product.price with min price
    _apply_min_price(pwc.product_id)

    return jsonify({
        'success': True,
        'message': 'Себестоимость добавлена',
        'data': pwc.to_dict()
    }), 201


@product_costs_bp.route('/<int:cost_id>', methods=['PUT'])
@jwt_required()
def update_product_cost(cost_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    pwc = ProductWarehouseCost.query.get(cost_id)
    if not pwc:
        return jsonify({'success': False, 'message': 'Не найдено'}), 404

    data = request.get_json()

    if 'cost_price' in data:
        pwc.cost_price = float(data['cost_price'])
        # Recalculate price
        _try_calculate(pwc)

    db.session.commit()

    # Update product.price with min price
    _apply_min_price(pwc.product_id)

    return jsonify({
        'success': True,
        'message': 'Себестоимость обновлена',
        'data': pwc.to_dict()
    }), 200


@product_costs_bp.route('/<int:cost_id>', methods=['DELETE'])
@jwt_required()
def delete_product_cost(cost_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    pwc = ProductWarehouseCost.query.get(cost_id)
    if not pwc:
        return jsonify({'success': False, 'message': 'Не найдено'}), 404

    product_id = pwc.product_id
    db.session.delete(pwc)
    db.session.commit()

    # Update product.price with min price (or keep manual if no costs left)
    _apply_min_price(product_id)

    return jsonify({'success': True, 'message': 'Удалено'}), 200


@product_costs_bp.route('/bulk', methods=['POST'])
@jwt_required()
def bulk_create_costs():
    """Bulk set cost prices for multiple products in a warehouse."""
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    data = request.get_json()
    warehouse_id = data.get('warehouse_id')
    items = data.get('items', [])  # [{product_id, cost_price}, ...]

    if not warehouse_id or not items:
        return jsonify({'success': False, 'message': 'warehouse_id и items обязательны'}), 400

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    created = 0
    updated = 0

    for item in items:
        product_id = item.get('product_id')
        cost_price = item.get('cost_price')

        if not product_id or cost_price is None:
            continue

        pwc = ProductWarehouseCost.query.filter_by(
            product_id=product_id,
            warehouse_id=warehouse_id
        ).first()

        if pwc:
            pwc.cost_price = float(cost_price)
            _try_calculate(pwc)
            updated += 1
        else:
            pwc = ProductWarehouseCost(
                product_id=product_id,
                warehouse_id=warehouse_id,
                cost_price=float(cost_price)
            )
            _try_calculate(pwc)
            db.session.add(pwc)
            created += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'Создано: {created}, обновлено: {updated}',
        'data': {'created': created, 'updated': updated}
    }), 200


def _try_calculate(pwc: ProductWarehouseCost):
    """Try to calculate price for a product-warehouse cost entry."""
    try:
        warehouse = Warehouse.query.get(pwc.warehouse_id)
        if not warehouse or not warehouse.formula:
            return

        currency_rate = warehouse.currency.rate_to_tenge if warehouse.currency else 1.0
        product_chars = extract_product_characteristics(pwc.product_id)

        # If no weight and no dimensions — price = 0, skip formula
        has_weight = product_chars.get('вес', 0) > 0
        has_dims = any(
            product_chars.get(f'размер_в_упаковке_{s}', 0) > 0 or
            product_chars.get(f'размер_без_упаковки_{s}', 0) > 0
            for s in ['длина', 'ширина', 'высота']
        )

        if not has_weight and not has_dims:
            pwc.calculated_price = 0
            pwc.calculated_at = datetime.now()
            return

        variables = WarehouseVariable.query.filter_by(warehouse_id=pwc.warehouse_id) \
            .order_by(WarehouseVariable.sort_order).all()
        var_list = [{'name': v.name, 'formula': v.formula} for v in variables]

        price, _ = calculate_product_price(
            cost_price=pwc.cost_price,
            currency_rate=currency_rate,
            product_characteristics=product_chars,
            warehouse_variables=var_list,
            final_formula=warehouse.formula.formula
        )

        pwc.calculated_price = round(price, 2)
        pwc.calculated_at = datetime.now()

    except (FormulaError, Exception):
        # If calculation fails, leave calculated_price as None
        pwc.calculated_price = None
        pwc.calculated_at = None


def _apply_min_price(product_id: int):
    """
    Find the minimum calculated_price for a product across all warehouses
    and write it to product.price + product.supplier_id.
    """
    from models.product import Product

    all_costs = ProductWarehouseCost.query.filter_by(product_id=product_id).all()

    best_cost = None
    for c in all_costs:
        if c.calculated_price and c.calculated_price > 0:
            if best_cost is None or c.calculated_price < best_cost.calculated_price:
                best_cost = c

    if best_cost:
        product = Product.query.get(product_id)
        if product:
            product.price = best_cost.calculated_price
            warehouse = Warehouse.query.get(best_cost.warehouse_id)
            if warehouse:
                product.supplier_id = warehouse.supplier_id
            db.session.commit()
