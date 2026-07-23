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
from utils.pricing_presets import MARGIN_VAR_NAME
from datetime import datetime
import re

product_costs_bp = Blueprint('product_costs', __name__)


# Имена «физических» переменных товара. Если хоть одна из формул склада
# (final / delivery / cost) ИЛИ его переменных косвенно использует одну
# из них — значит формула требует чтобы у товара были заполнены вес/габариты.
# \b — word-boundary, чтобы `вес` не матчился внутри `вес_упаковки` или
# подобных пользовательских имён.
_PHYSICAL_VAR_NAMES = (
    'вес', 'длина', 'ширина', 'высота', 'габариты',
    'Расчётный_вес',
    'размер_в_упаковке_длина', 'размер_в_упаковке_ширина', 'размер_в_упаковке_высота',
    'размер_без_упаковки_длина', 'размер_без_упаковки_ширина', 'размер_без_упаковки_высота',
)
_PHYSICAL_VAR_RE = re.compile(r'\b(' + '|'.join(_PHYSICAL_VAR_NAMES) + r')\b')


def _warehouse_uses_physical_vars(warehouse_formula, warehouse_variables):
    """Хоть одна из формул склада или его переменных ссылается на вес/габариты?"""
    formulas = [
        warehouse_formula.formula,
        warehouse_formula.delivery_formula,
        warehouse_formula.cost_formula,
    ]
    formulas.extend(v.formula for v in warehouse_variables)
    combined = ' '.join(f for f in formulas if f)
    return bool(_PHYSICAL_VAR_RE.search(combined))


def _product_has_dimensions(product_chars):
    """True если у товара есть вес ИЛИ хотя бы какие-то габариты (pack или nopack)."""
    if product_chars.get('вес', 0) > 0:
        return True
    for side in ('длина', 'ширина', 'высота'):
        if (product_chars.get(f'размер_в_упаковке_{side}', 0) > 0 or
            product_chars.get(f'размер_без_упаковки_{side}', 0) > 0):
            return True
    return False


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

    # Пре-фетчим переменную коэф_наценки для всех складов из выборки —
    # нужна корп.расчётнику чтобы инициализировать per-row наценку из
    # склада товара при добавлении в КП.
    warehouse_ids = list({c.warehouse_id for c in costs})
    margin_coefs = {}  # {warehouse_id: float | None}
    if warehouse_ids:
        margin_vars = WarehouseVariable.query.filter(
            WarehouseVariable.warehouse_id.in_(warehouse_ids),
            WarehouseVariable.name == MARGIN_VAR_NAME,
        ).all()
        for v in margin_vars:
            try:
                margin_coefs[v.warehouse_id] = float((v.formula or '').replace(',', '.').strip())
            except (ValueError, TypeError):
                margin_coefs[v.warehouse_id] = None

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
            data['currency_code'] = warehouse.currency.code if warehouse.currency else 'KZT'
            data['vat_enabled'] = bool(warehouse.vat_enabled)
        else:
            data['warehouse_name'] = None
            data['supplier_name'] = None
            data['currency_code'] = 'KZT'
            data['vat_enabled'] = True
        # Множитель торговой наценки со склада (переменная коэф_наценки).
        # Если переменная не задана простой константой — None; фронт
        # использует глобальный дефолт из шапки корп.расчётника.
        data['margin_coef'] = margin_coefs.get(c.warehouse_id)
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

    quantity = data.get('quantity', 0)
    try:
        quantity = max(0, int(quantity or 0))
    except (TypeError, ValueError):
        quantity = 0

    note = data.get('note')
    if note is not None and not isinstance(note, str):
        note = None

    pwc = ProductWarehouseCost(
        product_id=product_id,
        warehouse_id=warehouse_id,
        cost_price=float(cost_price),
        quantity=quantity,
        note=note,
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

    if 'quantity' in data:
        try:
            pwc.quantity = max(0, int(data['quantity'] or 0))
        except (TypeError, ValueError):
            pwc.quantity = 0

    if 'note' in data:
        note = data.get('note')
        pwc.note = note if isinstance(note, str) else None

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
    affected_product_ids = set()

    for item in items:
        product_id = item.get('product_id')
        cost_price = item.get('cost_price')
        quantity_in = item.get('quantity')

        if not product_id or cost_price is None:
            continue

        try:
            quantity = max(0, int(quantity_in or 0)) if quantity_in is not None else None
        except (TypeError, ValueError):
            quantity = None

        pwc = ProductWarehouseCost.query.filter_by(
            product_id=product_id,
            warehouse_id=warehouse_id
        ).first()

        if pwc:
            pwc.cost_price = float(cost_price)
            if quantity is not None:
                pwc.quantity = quantity
            _try_calculate(pwc)
            updated += 1
        else:
            pwc = ProductWarehouseCost(
                product_id=product_id,
                warehouse_id=warehouse_id,
                cost_price=float(cost_price),
                quantity=quantity if quantity is not None else 0
            )
            _try_calculate(pwc)
            db.session.add(pwc)
            created += 1

        affected_product_ids.add(product_id)

    db.session.commit()

    # Пересчитать product.price/quantity/supplier_id для всех затронутых
    for pid in affected_product_ids:
        _apply_min_price(pid)

    return jsonify({
        'success': True,
        'message': f'Создано: {created}, обновлено: {updated}',
        'data': {'created': created, 'updated': updated}
    }), 200


@product_costs_bp.route('/upsert-many', methods=['POST'])
@jwt_required()
def upsert_many_costs():
    """
    Для одного товара upsert закупок/остатков сразу на несколько складов.
    Один запрос вместо N (POST → 400 → GET → PUT) на каждый склад. Ускоряет
    миграции вроде Equip, где у товара 9-10 закупок на разных warehouses.

    Body: {
        "product_id": int,
        "supplier_id": int,    # ОБЯЗАТЕЛЬНО при prune=true
        "prune": bool,         # default false
        "items": [
            {"warehouse_id": int, "cost_price": float, "quantity": int}, ...
        ]
    }

    prune=true: после upsert удаляются записи product_warehouse_cost
    этого товара, у которых warehouse.supplier_id == указанному supplier_id
    И warehouse_id НЕ в items. Используется регулярными синками когда
    у товара пропадают склады в источнике (Equip API). Ограничено по
    supplier_id чтобы случайно не снести записи другого поставщика
    (например, BIO для того же товара после дедупа по имени).

    После всего одного коммита один раз вызываем _apply_min_price.
    """
    if not check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    data = request.get_json() or {}
    product_id = data.get('product_id')
    items = data.get('items') or []
    prune = bool(data.get('prune'))
    supplier_id = data.get('supplier_id')

    if not product_id:
        return jsonify({'success': False, 'message': 'product_id обязателен'}), 400
    if prune and not supplier_id:
        # Безопасность: prune без supplier_id мог бы стереть записи
        # другого поставщика для того же товара.
        return jsonify({'success': False, 'message': 'prune=true требует supplier_id'}), 400
    if not items and not prune:
        return jsonify({'success': False, 'message': 'items обязательны (или prune=true для очистки)'}), 400

    # Один запрос — поднимаем все существующие записи этого товара
    existing_by_wh = {
        c.warehouse_id: c
        for c in ProductWarehouseCost.query.filter_by(product_id=product_id).all()
    }

    created = 0
    updated = 0
    skipped = 0
    sent_warehouse_ids = set()

    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        wh_id = item.get('warehouse_id')
        cost_price = item.get('cost_price')
        if not wh_id or cost_price is None:
            skipped += 1
            continue
        try:
            qty = max(0, int(item.get('quantity') or 0))
        except (TypeError, ValueError):
            qty = 0

        # note опционально — если передали (даже пустую строку),
        # перетираем; если ключа нет — оставляем как было.
        note = item.get('note') if 'note' in item else None
        has_note_key = 'note' in item

        sent_warehouse_ids.add(wh_id)
        pwc = existing_by_wh.get(wh_id)
        if pwc:
            pwc.cost_price = float(cost_price)
            pwc.quantity = qty
            if has_note_key:
                pwc.note = note if isinstance(note, str) else None
            _try_calculate(pwc)
            updated += 1
        else:
            pwc = ProductWarehouseCost(
                product_id=product_id,
                warehouse_id=wh_id,
                cost_price=float(cost_price),
                quantity=qty,
                note=note if has_note_key and isinstance(note, str) else None,
            )
            _try_calculate(pwc)
            db.session.add(pwc)
            existing_by_wh[wh_id] = pwc
            created += 1

    pruned = 0
    if prune:
        # Удаляем cost-записи этого товара ТОЛЬКО на складах указанного
        # поставщика, которых не было в items. Например, Equip перестал
        # везти товар в Екатеринбург — соответствующая запись (с её
        # старыми quantity и calculated_price) уходит.
        from models.warehouse import Warehouse
        stale_q = (
            ProductWarehouseCost.query
            .join(Warehouse, Warehouse.id == ProductWarehouseCost.warehouse_id)
            .filter(
                ProductWarehouseCost.product_id == product_id,
                Warehouse.supplier_id == supplier_id,
            )
        )
        if sent_warehouse_ids:
            stale_q = stale_q.filter(~ProductWarehouseCost.warehouse_id.in_(sent_warehouse_ids))
        for stale_pwc in stale_q.all():
            db.session.delete(stale_pwc)
            pruned += 1

    db.session.commit()
    # Один пересчёт min-price на товар, не N как было.
    _apply_min_price(product_id)

    return jsonify({
        'success': True,
        'data': {'created': created, 'updated': updated, 'skipped': skipped, 'pruned': pruned},
    }), 200


def _try_calculate(pwc: ProductWarehouseCost):
    """Try to calculate price for a product-warehouse cost entry."""
    try:
        warehouse = Warehouse.query.get(pwc.warehouse_id)
        if not warehouse or not warehouse.formula:
            return

        currency_rate = warehouse.currency.rate_to_tenge if warehouse.currency else 1.0
        product_chars = extract_product_characteristics(pwc.product_id)

        variables = WarehouseVariable.query.filter_by(warehouse_id=pwc.warehouse_id) \
            .order_by(WarehouseVariable.sort_order).all()

        # Умная защита: если хоть одна формула склада (цена/доставка/себестоимость/
        # переменные) использует физические переменные товара (вес, габариты),
        # а у товара они не заполнены — не считаем, ставим розницу в 0. Это
        # сигнализирует в админке и на витрине что товару нужны характеристики.
        # Для простых формул типа `себестоимость * маржа` блок не активируется
        # и расчёт идёт как обычно.
        if _warehouse_uses_physical_vars(warehouse.formula, variables) \
                and not _product_has_dimensions(product_chars):
            pwc.calculated_price = 0
            pwc.calculated_delivery = None
            pwc.calculated_cost_no_margin = None
            pwc.calculated_at = datetime.now()
            return
        var_list = [{'name': v.name, 'formula': v.formula} for v in variables]

        # Сначала считаем доставку — её результат становится переменной
        # `доставка`, доступной в формуле розничной цены. Это позволяет
        # шаблонам розницы (РФ / КЗ_с_НДС / КЗ_без_НДС) ссылаться на
        # доставку простым именем без дублирования выражения.
        delivery_value = 0.0
        if warehouse.formula.delivery_formula:
            try:
                delivery_value, _ = calculate_product_price(
                    cost_price=pwc.cost_price,
                    currency_rate=currency_rate,
                    product_characteristics=product_chars,
                    warehouse_variables=var_list,
                    final_formula=warehouse.formula.delivery_formula
                )
                pwc.calculated_delivery = round(delivery_value, 2)
            except (FormulaError, Exception):
                pwc.calculated_delivery = None
                delivery_value = 0.0
        else:
            pwc.calculated_delivery = None

        # В расчёт цены пробрасываем `Доставка` как дополнительную переменную.
        price_var_list = var_list + [{'name': 'Доставка', 'formula': str(delivery_value)}]

        price, all_vars = calculate_product_price(
            cost_price=pwc.cost_price,
            currency_rate=currency_rate,
            product_characteristics=product_chars,
            warehouse_variables=price_var_list,
            final_formula=warehouse.formula.formula
        )

        pwc.calculated_price = round(price, 2)
        pwc.calculated_at = datetime.now()

        # Себестоимость без маржи — третья формула склада. Считаем тут же,
        # чтобы upsert закупки сразу перегонял все три значения и не нужно
        # было после миграций (Equip/BIO) руками жать «Пересчитать склад».
        # Если формула не задана — не трогаем старое значение (см. bulk recalc).
        if warehouse.formula.cost_formula:
            try:
                cost_no_margin, _ = calculate_product_price(
                    cost_price=pwc.cost_price,
                    currency_rate=currency_rate,
                    product_characteristics=product_chars,
                    warehouse_variables=var_list,
                    final_formula=warehouse.formula.cost_formula
                )
                pwc.calculated_cost_no_margin = round(cost_no_margin, 2)
            except (FormulaError, Exception):
                pwc.calculated_cost_no_margin = None

    except (FormulaError, Exception):
        # If calculation fails, leave calculated_price as None
        pwc.calculated_price = None
        pwc.calculated_delivery = None
        pwc.calculated_cost_no_margin = None
        pwc.calculated_at = None


def _apply_min_price(product_id: int):
    """
    Найти минимальную calculated_price среди складов и записать в product.

    Приоритет: сначала ищем склад с минимумом среди тех, где quantity > 0
    (товар реально доступен) — оттуда берём цену, поставщика И остаток.
    Если в наличии нигде нет — берём минимум без учёта остатка
    (как «теоретическая» цена при поступлении), а quantity ставим 0.
    """
    from models.product import Product

    all_costs = ProductWarehouseCost.query.filter_by(product_id=product_id).all()

    in_stock = [c for c in all_costs if c.calculated_price and c.calculated_price > 0 and (c.quantity or 0) > 0]
    fallback = [c for c in all_costs if c.calculated_price and c.calculated_price > 0]

    best_cost = None
    use_quantity = False

    if in_stock:
        best_cost = min(in_stock, key=lambda c: c.calculated_price)
        use_quantity = True
    elif fallback:
        best_cost = min(fallback, key=lambda c: c.calculated_price)

    if not best_cost:
        return

    product = Product.query.get(product_id)
    if not product:
        return

    product.price = best_cost.calculated_price
    warehouse = Warehouse.query.get(best_cost.warehouse_id)
    if warehouse:
        product.supplier_id = warehouse.supplier_id
    product.quantity = (best_cost.quantity or 0) if use_quantity else 0
    db.session.commit()
