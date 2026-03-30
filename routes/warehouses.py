from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.warehouse import Warehouse, WarehouseVariable, WarehouseFormula
from models.product_warehouse_cost import ProductWarehouseCost
from models.currency import Currency
from utils.formula_engine import (
    validate_formula, calculate_product_price,
    extract_product_characteristics, BUILTIN_VARIABLE_NAMES,
    FormulaError
)
from datetime import datetime

warehouses_bp = Blueprint('warehouses', __name__)


def check_admin():
    jwt_data = get_jwt()
    role = jwt_data.get('role')
    if role not in ('admin', 'system'):
        return False
    return True


# ============ Warehouse CRUD ============

@warehouses_bp.route('/', methods=['GET'])
@jwt_required()
def get_warehouses():
    supplier_id = request.args.get('supplier_id', type=int)

    query = Warehouse.query
    if supplier_id:
        query = query.filter_by(supplier_id=supplier_id)

    warehouses = query.order_by(Warehouse.name).all()

    result = []
    for w in warehouses:
        data = w.to_dict()
        data['product_count'] = ProductWarehouseCost.query.filter_by(warehouse_id=w.id).count()
        data['has_formula'] = w.formula is not None
        result.append(data)

    return jsonify({
        'success': True,
        'data': result,
        'count': len(result)
    }), 200


@warehouses_bp.route('/<int:warehouse_id>', methods=['GET'])
@jwt_required()
def get_warehouse(warehouse_id):
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = warehouse.to_dict_full()
    data['product_count'] = ProductWarehouseCost.query.filter_by(warehouse_id=warehouse_id).count()
    return jsonify({'success': True, 'data': data}), 200


@warehouses_bp.route('/', methods=['POST'])
@jwt_required()
def create_warehouse():
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Нет данных'}), 400

    required = ['supplier_id', 'name', 'currency_id']
    for field in required:
        if field not in data:
            return jsonify({'success': False, 'message': f'Обязательное поле: {field}'}), 400

    # Verify currency exists
    currency = Currency.query.get(data['currency_id'])
    if not currency:
        return jsonify({'success': False, 'message': 'Валюта не найдена'}), 404

    warehouse = Warehouse(
        supplier_id=data['supplier_id'],
        name=data['name'].strip(),
        city=data.get('city', '').strip() if data.get('city') else None,
        address=data.get('address', '').strip() if data.get('address') else None,
        currency_id=data['currency_id']
    )
    db.session.add(warehouse)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Склад создан',
        'data': warehouse.to_dict()
    }), 201


@warehouses_bp.route('/<int:warehouse_id>', methods=['PUT'])
@jwt_required()
def update_warehouse(warehouse_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = request.get_json()

    if 'name' in data:
        warehouse.name = data['name'].strip()
    if 'city' in data:
        warehouse.city = data['city'].strip() if data['city'] else None
    if 'address' in data:
        warehouse.address = data['address'].strip() if data['address'] else None
    if 'currency_id' in data:
        currency = Currency.query.get(data['currency_id'])
        if not currency:
            return jsonify({'success': False, 'message': 'Валюта не найдена'}), 404
        warehouse.currency_id = data['currency_id']

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Склад обновлён',
        'data': warehouse.to_dict()
    }), 200


@warehouses_bp.route('/<int:warehouse_id>', methods=['DELETE'])
@jwt_required()
def delete_warehouse(warehouse_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    db.session.delete(warehouse)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Склад удалён'}), 200


# ============ Variables ============

@warehouses_bp.route('/<int:warehouse_id>/variables', methods=['GET'])
@jwt_required()
def get_variables(warehouse_id):
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    variables = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
        .order_by(WarehouseVariable.sort_order).all()

    return jsonify({
        'success': True,
        'data': [v.to_dict() for v in variables]
    }), 200


@warehouses_bp.route('/<int:warehouse_id>/variables', methods=['POST'])
@jwt_required()
def save_variables(warehouse_id):
    """Bulk save variables (replace all)."""
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = request.get_json()
    variables_data = data.get('variables', [])

    # Validate all variable names and formulas
    known_vars = set(BUILTIN_VARIABLE_NAMES)
    for i, var in enumerate(variables_data):
        name = var.get('name', '').strip()
        formula = var.get('formula', '').strip()

        if not name:
            return jsonify({'success': False, 'message': f'Переменная #{i+1}: имя не может быть пустым'}), 400
        if not formula:
            return jsonify({'success': False, 'message': f'Переменная "{name}": формула не может быть пустой'}), 400

        # Variable name should be valid identifier
        if not name.replace('_', '').replace('а', 'a').isalnum():
            pass  # Allow Russian names

        # Validate formula with currently known vars
        error = validate_formula(formula, known_vars)
        if error:
            return jsonify({
                'success': False,
                'message': f'Переменная "{name}": {error}'
            }), 400

        known_vars.add(name)

    # Delete old variables
    WarehouseVariable.query.filter_by(warehouse_id=warehouse_id).delete()

    # Create new variables
    for i, var in enumerate(variables_data):
        new_var = WarehouseVariable(
            warehouse_id=warehouse_id,
            name=var['name'].strip(),
            label=var.get('label', '').strip() if var.get('label') else None,
            formula=var['formula'].strip(),
            sort_order=i
        )
        db.session.add(new_var)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Переменные сохранены'
    }), 200


@warehouses_bp.route('/<int:warehouse_id>/variables/single', methods=['POST'])
@jwt_required()
def save_single_variable(warehouse_id):
    """Create or update a single variable."""
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = request.get_json()
    var_id = data.get('id')
    name = data.get('name', '').strip()
    label = data.get('label', '').strip() if data.get('label') else None
    formula = data.get('formula', '').strip()
    sort_order = data.get('sort_order', 0)

    if not name:
        return jsonify({'success': False, 'message': 'Имя переменной обязательно'}), 400
    if not formula:
        return jsonify({'success': False, 'message': 'Формула обязательна'}), 400

    # Build known vars: builtins + vars_above (sent from client — reflects current UI order)
    known_vars = set(BUILTIN_VARIABLE_NAMES)
    vars_above = data.get('vars_above', [])
    if vars_above:
        for vname in vars_above:
            known_vars.add(vname)
    else:
        # Fallback: use DB order
        other_vars = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
            .order_by(WarehouseVariable.sort_order).all()
        for v in other_vars:
            if v.sort_order < sort_order and (not var_id or v.id != var_id):
                known_vars.add(v.name)

    # Validate formula
    error = validate_formula(formula, known_vars)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    if var_id:
        # Update existing
        variable = WarehouseVariable.query.get(var_id)
        if not variable or variable.warehouse_id != warehouse_id:
            return jsonify({'success': False, 'message': 'Переменная не найдена'}), 404
        variable.name = name
        variable.label = label
        variable.formula = formula
        variable.sort_order = sort_order
    else:
        # Create new
        variable = WarehouseVariable(
            warehouse_id=warehouse_id,
            name=name,
            label=label,
            formula=formula,
            sort_order=sort_order
        )
        db.session.add(variable)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'Переменная "{name}" сохранена',
        'data': variable.to_dict()
    }), 200


@warehouses_bp.route('/<int:warehouse_id>/variables/<int:variable_id>', methods=['DELETE'])
@jwt_required()
def delete_variable(warehouse_id, variable_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    variable = WarehouseVariable.query.get(variable_id)
    if not variable or variable.warehouse_id != warehouse_id:
        return jsonify({'success': False, 'message': 'Переменная не найдена'}), 404

    db.session.delete(variable)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Переменная удалена'}), 200


# ============ Formula ============

@warehouses_bp.route('/<int:warehouse_id>/formula', methods=['GET'])
@jwt_required()
def get_formula(warehouse_id):
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    formula = WarehouseFormula.query.filter_by(warehouse_id=warehouse_id).first()
    return jsonify({
        'success': True,
        'data': formula.to_dict() if formula else None
    }), 200


@warehouses_bp.route('/<int:warehouse_id>/formula', methods=['PUT'])
@jwt_required()
def save_formula(warehouse_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = request.get_json()
    formula_text = data.get('formula', '').strip()
    delivery_formula_text = data.get('delivery_formula', '').strip() if data.get('delivery_formula') else None

    if not formula_text:
        return jsonify({'success': False, 'message': 'Формула не может быть пустой'}), 400

    # Get all available variable names
    variables = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
        .order_by(WarehouseVariable.sort_order).all()
    available_vars = set(BUILTIN_VARIABLE_NAMES)
    for v in variables:
        available_vars.add(v.name)

    # Validate price formula
    error = validate_formula(formula_text, available_vars)
    if error:
        return jsonify({'success': False, 'message': f'Формула цены: {error}'}), 400

    # Validate delivery formula if provided
    if delivery_formula_text:
        error = validate_formula(delivery_formula_text, available_vars)
        if error:
            return jsonify({'success': False, 'message': f'Формула доставки: {error}'}), 400

    # Save or update
    formula = WarehouseFormula.query.filter_by(warehouse_id=warehouse_id).first()
    if formula:
        formula.formula = formula_text
        formula.delivery_formula = delivery_formula_text
        formula.updated_at = datetime.now()
    else:
        formula = WarehouseFormula(
            warehouse_id=warehouse_id,
            formula=formula_text,
            delivery_formula=delivery_formula_text
        )
        db.session.add(formula)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Формулы сохранены',
        'data': formula.to_dict()
    }), 200


@warehouses_bp.route('/<int:warehouse_id>/formula', methods=['DELETE'])
@jwt_required()
def delete_formula(warehouse_id):
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    formula = WarehouseFormula.query.filter_by(warehouse_id=warehouse_id).first()
    if not formula:
        return jsonify({'success': False, 'message': 'Формула не найдена'}), 404

    db.session.delete(formula)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Формула удалена'}), 200


# ============ Validate & Preview ============

@warehouses_bp.route('/<int:warehouse_id>/validate-formula', methods=['POST'])
@jwt_required()
def validate_warehouse_formula(warehouse_id):
    """Validate a formula without saving it."""
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = request.get_json()
    formula_text = data.get('formula', '').strip()

    variables = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
        .order_by(WarehouseVariable.sort_order).all()
    available_vars = set(BUILTIN_VARIABLE_NAMES)
    for v in variables:
        available_vars.add(v.name)

    error = validate_formula(formula_text, available_vars)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    return jsonify({'success': True, 'message': 'Формула корректна'}), 200


@warehouses_bp.route('/<int:warehouse_id>/calculate-preview', methods=['POST'])
@jwt_required()
def calculate_preview(warehouse_id):
    """Preview price calculation. product_id is optional (for characteristics)."""
    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    data = request.get_json()
    product_id = data.get('product_id')
    cost_price = data.get('cost_price')
    # Optional manual characteristics for preview without product
    manual_weight = data.get('weight', 0)
    manual_dimensions = data.get('dimensions', 0)

    if cost_price is None:
        if product_id:
            pwc = ProductWarehouseCost.query.filter_by(
                product_id=product_id,
                warehouse_id=warehouse_id
            ).first()
            if pwc:
                cost_price = pwc.cost_price
        if cost_price is None:
            return jsonify({'success': False, 'message': 'Себестоимость не указана'}), 400

    # Get formula
    if not warehouse.formula:
        return jsonify({'success': False, 'message': 'Формула не задана'}), 400

    # Get currency rate
    currency_rate = warehouse.currency.rate_to_tenge if warehouse.currency else 1.0

    # Get product characteristics or use manual values
    if product_id:
        product_chars = extract_product_characteristics(product_id)
    else:
        product_chars = {}

    # Override with manual values if provided
    if manual_weight:
        product_chars['вес'] = float(manual_weight)
    if manual_dimensions:
        # manual_dimensions is the volume product (Д*Ш*В) in mm
        # Parse as "ДxШxВ" string or plain number
        dims_str = str(manual_dimensions)
        from utils.formula_engine import _parse_dimensions
        parsed = _parse_dimensions(dims_str)
        if parsed:
            product_chars['размер_в_упаковке_длина'] = parsed[0]
            product_chars['размер_в_упаковке_ширина'] = parsed[1]
            product_chars['размер_в_упаковке_высота'] = parsed[2]

    # Get variables
    variables = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
        .order_by(WarehouseVariable.sort_order).all()
    var_list = [{'name': v.name, 'formula': v.formula} for v in variables]

    try:
        price, all_vars = calculate_product_price(
            cost_price=float(cost_price),
            currency_rate=currency_rate,
            product_characteristics=product_chars,
            warehouse_variables=var_list,
            final_formula=warehouse.formula.formula
        )

        # Build step-by-step breakdown
        steps = []
        steps.append({'name': 'себестоимость', 'value': round(float(cost_price), 2)})
        steps.append({'name': 'курс_валюты', 'value': round(currency_rate, 4)})

        for v in var_list:
            val = all_vars.get(v['name'], 0)
            steps.append({
                'name': v['name'],
                'formula': v['formula'],
                'value': round(val, 4)
            })

        steps.append({
            'name': 'Итоговая цена',
            'formula': warehouse.formula.formula,
            'value': round(price, 2)
        })

        return jsonify({
            'success': True,
            'data': {
                'calculated_price': round(price, 2),
                'variables': {k: round(v, 4) for k, v in all_vars.items()},
                'steps': steps,
                'formula': warehouse.formula.formula
            }
        }), 200

    except FormulaError as e:
        return jsonify({'success': False, 'message': str(e)}), 400


# ============ Recalculate ============

@warehouses_bp.route('/<int:warehouse_id>/recalculate', methods=['POST'])
@jwt_required()
def recalculate_warehouse(warehouse_id):
    """Recalculate prices for all products in a warehouse."""
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    if not warehouse.formula:
        return jsonify({'success': False, 'message': 'Формула не задана'}), 400

    currency_rate = warehouse.currency.rate_to_tenge if warehouse.currency else 1.0

    variables = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
        .order_by(WarehouseVariable.sort_order).all()
    var_list = [{'name': v.name, 'formula': v.formula} for v in variables]

    costs = ProductWarehouseCost.query.filter_by(warehouse_id=warehouse_id).all()

    success_count = 0
    error_count = 0
    errors = []

    for pwc in costs:
        try:
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
                success_count += 1
                continue

            price, _ = calculate_product_price(
                cost_price=pwc.cost_price,
                currency_rate=currency_rate,
                product_characteristics=product_chars,
                warehouse_variables=var_list,
                final_formula=warehouse.formula.formula
            )
            pwc.calculated_price = round(price, 2)
            pwc.calculated_at = datetime.now()
            success_count += 1
        except FormulaError as e:
            error_count += 1
            product_name = pwc.product.name if pwc.product else f'ID {pwc.product_id}'
            errors.append(f'{product_name}: {str(e)}')

    db.session.commit()

    # Update product.price and product.supplier_id with min price across all warehouses
    _update_product_prices_from_warehouse(warehouse_id)

    return jsonify({
        'success': True,
        'message': f'Пересчитано: {success_count}, ошибок: {error_count}',
        'data': {
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors[:20]  # Limit error list
        }
    }), 200


def _update_product_prices_from_warehouse(warehouse_id: int):
    """
    For each product on this warehouse, find the min calculated_price
    across ALL warehouses and update product.price + product.supplier_id.
    """
    from models.product import Product

    costs = ProductWarehouseCost.query.filter_by(warehouse_id=warehouse_id).all()
    product_ids = set(c.product_id for c in costs)

    for product_id in product_ids:
        _apply_min_price_to_product(product_id)


def _apply_min_price_to_product(product_id: int):
    """
    Find the minimum calculated_price for a product across all warehouses
    and write it to product.price + product.supplier_id.
    """
    from models.product import Product

    all_costs = ProductWarehouseCost.query.filter_by(product_id=product_id).all()

    # Find min price among costs with calculated_price > 0
    best_cost = None
    for c in all_costs:
        if c.calculated_price and c.calculated_price > 0:
            if best_cost is None or c.calculated_price < best_cost.calculated_price:
                best_cost = c

    if best_cost:
        product = Product.query.get(product_id)
        if product:
            product.price = best_cost.calculated_price
            # Set supplier from the warehouse with min price
            warehouse = Warehouse.query.get(best_cost.warehouse_id)
            if warehouse:
                product.supplier_id = warehouse.supplier_id
            db.session.commit()
