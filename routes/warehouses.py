from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.warehouse import Warehouse, WarehouseVariable, WarehouseFormula
from models.product_warehouse_cost import ProductWarehouseCost
from models.currency import Currency
from utils.formula_engine import (
    validate_formula, calculate_product_price,
    extract_product_characteristics, bulk_extract_product_characteristics,
    BUILTIN_VARIABLE_NAMES, FormulaError
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

import threading

# In-memory storage for recalculation status
_recalc_status = {}


def _do_recalculate(app, warehouse_id, currency_rate, var_list, cost_ids, formula_text, delivery_formula_text):
    """Background recalculation worker."""
    status = _recalc_status[warehouse_id]
    try:
        with app.app_context():
            BATCH_SIZE = 100
            for batch_start in range(0, len(cost_ids), BATCH_SIZE):
                batch_ids = cost_ids[batch_start:batch_start + BATCH_SIZE]

                try:
                    batch_costs = ProductWarehouseCost.query.filter(ProductWarehouseCost.id.in_(batch_ids)).all()
                    batch_product_ids = [pwc.product_id for pwc in batch_costs]
                    all_chars = bulk_extract_product_characteristics(batch_product_ids)
                except Exception as e:
                    # DB connection error — rollback and retry once
                    db.session.rollback()
                    try:
                        batch_costs = ProductWarehouseCost.query.filter(ProductWarehouseCost.id.in_(batch_ids)).all()
                        batch_product_ids = [pwc.product_id for pwc in batch_costs]
                        all_chars = bulk_extract_product_characteristics(batch_product_ids)
                    except Exception as e2:
                        status['error_count'] += len(batch_ids)
                        status['processed'] += len(batch_ids)
                        if len(status['errors']) < 20:
                            status['errors'].append(f'Batch error: {str(e2)[:100]}')
                        continue

                for pwc in batch_costs:
                    try:
                        product_chars = all_chars.get(pwc.product_id, {})
                        has_weight = product_chars.get('вес', 0) > 0
                        has_dims = any(
                            product_chars.get(f'размер_в_упаковке_{s}', 0) > 0 or
                            product_chars.get(f'размер_без_упаковки_{s}', 0) > 0
                            for s in ['длина', 'ширина', 'высота']
                        )

                        if not has_weight and not has_dims:
                            pwc.calculated_price = 0
                            pwc.calculated_delivery = None
                            pwc.calculated_at = datetime.now()
                            status['zero_price'] += 1
                            product_name = pwc.product.name if pwc.product else f'ID {pwc.product_id}'
                            status['zero_price_reasons'].append({'name': product_name, 'reason': 'Нет веса и габаритов'})
                            status['processed'] += 1
                            continue

                        price, _ = calculate_product_price(
                            cost_price=pwc.cost_price,
                            currency_rate=currency_rate,
                            product_characteristics=product_chars,
                            warehouse_variables=var_list,
                            final_formula=formula_text
                        )
                        pwc.calculated_price = round(price, 2)
                        pwc.calculated_at = datetime.now()
                        status['price_calculated'] += 1

                        if delivery_formula_text:
                            try:
                                delivery, _ = calculate_product_price(
                                    cost_price=pwc.cost_price,
                                    currency_rate=currency_rate,
                                    product_characteristics=product_chars,
                                    warehouse_variables=var_list,
                                    final_formula=delivery_formula_text
                                )
                                pwc.calculated_delivery = round(delivery, 2)
                                status['delivery_calculated'] += 1
                            except (FormulaError, Exception):
                                pwc.calculated_delivery = None
                        else:
                            pwc.calculated_delivery = None

                        status['processed'] += 1
                    except FormulaError as e:
                        status['error_count'] += 1
                        product_name = pwc.product.name if pwc.product else f'ID {pwc.product_id}'
                        if len(status['errors']) < 20:
                            status['errors'].append(f'{product_name}: {str(e)}')
                        status['processed'] += 1

                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    if len(status['errors']) < 20:
                        status['errors'].append(f'Commit error: {str(e)[:100]}')

            try:
                _update_product_prices_from_warehouse(warehouse_id)
            except Exception:
                db.session.rollback()

            status['status'] = 'done'
            status['finished_at'] = datetime.utcnow().isoformat() + 'Z'
    except Exception as e:
        status['status'] = 'error'
        status['finished_at'] = datetime.utcnow().isoformat() + 'Z'
        if len(status['errors']) < 20:
            status['errors'].append(f'Fatal: {str(e)[:200]}')

    # Persist results to DB
    try:
        with app.app_context():
            wh = Warehouse.query.get(warehouse_id)
            if wh:
                wh.last_recalc = {k: v for k, v in status.items()}
                db.session.commit()
    except Exception:
        pass


@warehouses_bp.route('/<int:warehouse_id>/recalculate', methods=['POST'])
@jwt_required()
def recalculate_warehouse(warehouse_id):
    """Start async recalculation for all products in a warehouse."""
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    warehouse = Warehouse.query.get(warehouse_id)
    if not warehouse:
        return jsonify({'success': False, 'message': 'Склад не найден'}), 404

    if not warehouse.formula:
        return jsonify({'success': False, 'message': 'Формула не задана'}), 400

    # Check if already running
    if warehouse_id in _recalc_status and _recalc_status[warehouse_id]['status'] == 'running':
        s = _recalc_status[warehouse_id]
        return jsonify({
            'success': True,
            'message': f'Уже выполняется: {s["processed"]}/{s["total"]}',
            'data': {**s}
        }), 200

    # Refresh RUB rate from Halyk Bank before recalculation
    rate_refreshed = None
    if warehouse.currency and warehouse.currency.code == 'RUB':
        try:
            from utils.currency_rates import fetch_rub_rate_halyk
            new_rate = fetch_rub_rate_halyk()
            old_rate = warehouse.currency.rate_to_tenge
            warehouse.currency.rate_to_tenge = new_rate
            db.session.commit()
            rate_refreshed = {'old': old_rate, 'new': new_rate}
        except Exception as e:
            rate_refreshed = {'error': str(e)}

    currency_rate = warehouse.currency.rate_to_tenge if warehouse.currency else 1.0
    variables = WarehouseVariable.query.filter_by(warehouse_id=warehouse_id) \
        .order_by(WarehouseVariable.sort_order).all()
    var_list = [{'name': v.name, 'formula': v.formula} for v in variables]

    cost_ids = [c.id for c in ProductWarehouseCost.query.filter_by(warehouse_id=warehouse_id).with_entities(ProductWarehouseCost.id).all()]

    delivery_formula_text = warehouse.formula.delivery_formula

    _recalc_status[warehouse_id] = {
        'status': 'running',
        'started_at': datetime.utcnow().isoformat() + 'Z',
        'finished_at': None,
        'total': len(cost_ids),
        'processed': 0,
        'price_calculated': 0,
        'delivery_calculated': 0,
        'zero_price': 0,
        'zero_price_reasons': [],
        'error_count': 0,
        'errors': [],
        'has_delivery_formula': bool(delivery_formula_text),
        'currency_rate': currency_rate,
        'rate_refreshed': rate_refreshed,
    }

    from flask import current_app
    app = current_app._get_current_object()

    thread = threading.Thread(
        target=_do_recalculate,
        args=(app, warehouse_id, currency_rate, var_list, cost_ids,
              warehouse.formula.formula, delivery_formula_text),
        daemon=True
    )
    thread.start()

    return jsonify({
        'success': True,
        'message': f'Пересчёт запущен: {len(cost_ids)} товаров',
        'data': _recalc_status[warehouse_id]
    }), 200


@warehouses_bp.route('/<int:warehouse_id>/recalculate-status', methods=['GET'])
@jwt_required()
def recalculate_status(warehouse_id):
    """Check recalculation progress."""
    status = _recalc_status.get(warehouse_id)
    if not status:
        # Try loading from DB
        wh = Warehouse.query.get(warehouse_id)
        if wh and wh.last_recalc:
            return jsonify({
                'success': True,
                'message': f'Последний пересчёт: {wh.last_recalc.get("processed", 0)}/{wh.last_recalc.get("total", 0)}',
                'data': wh.last_recalc
            }), 200
        return jsonify({'success': True, 'data': None}), 200

    return jsonify({
        'success': True,
        'message': f'{"Завершено" if status["status"] == "done" else "Выполняется"}: {status["processed"]}/{status["total"]}',
        'data': {**status}
    }), 200


def _update_product_prices_from_warehouse(warehouse_id: int):
    """
    For each product on this warehouse, find the min calculated_price
    across ALL warehouses and update product.price + product.supplier_id.
    Uses raw SQL for performance (handles 12k+ products in seconds).
    """
    # Single SQL: find min price per product across all warehouses, then bulk update
    db.session.execute(db.text("""
        UPDATE product p
        SET price = best.min_price,
            supplier_id = best.best_supplier_id
        FROM (
            SELECT DISTINCT ON (pwc.product_id)
                pwc.product_id,
                pwc.calculated_price AS min_price,
                w.supplier_id AS best_supplier_id
            FROM product_warehouse_cost pwc
            JOIN warehouse w ON w.id = pwc.warehouse_id
            WHERE pwc.calculated_price > 0
              AND pwc.product_id IN (
                  SELECT product_id FROM product_warehouse_cost WHERE warehouse_id = :wid
              )
            ORDER BY pwc.product_id, pwc.calculated_price ASC
        ) best
        WHERE p.id = best.product_id
    """), {'wid': warehouse_id})
    db.session.commit()
