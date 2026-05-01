from flask import Blueprint, request, jsonify
from extensions import db
from models.characteristic import ProductCharacteristic
from models.characteristics_list import CharacteristicsList

characteristics_bp = Blueprint('characteristics', __name__)


@characteristics_bp.route('/<int:product_id>', methods=['GET'])
def get_characteristics(product_id):
    chars = ProductCharacteristic.query.filter_by(product_id=product_id).order_by(
        ProductCharacteristic.sort_order).all()
    
    result = []
    for c in chars:
        # Получаем данные из справочника характеристик по ID из поля key
        try:
            characteristic_id = int(c.key) if c.key else None
        except (ValueError, TypeError):
            characteristic_id = None
            
        if characteristic_id:
            characteristic_info = CharacteristicsList.query.get(characteristic_id)
            if characteristic_info:
                result.append({
                    'id': c.id,
                    'characteristic_id': characteristic_id,
                    'key': characteristic_info.characteristic_key,
                    'value': c.value,
                    'unit_of_measurement': characteristic_info.unit_of_measurement or '',
                    'sort_order': c.sort_order
                })
    
    return jsonify(result)


@characteristics_bp.route('/<int:product_id>', methods=['POST'])
def add_characteristic(product_id):
    data = request.json
    char = ProductCharacteristic(
        product_id=product_id,
        key=str(data['characteristic_id']),  # Сохраняем ID как строку в поле key
        value=data['value'],
        sort_order=data.get('sort_order', 0)
    )
    db.session.add(char)
    db.session.commit()
    return jsonify({'message': 'Characteristic added'}), 201


@characteristics_bp.route('/<int:product_id>/bulk-by-key', methods=['POST'])
def add_characteristics_bulk_by_key(product_id):
    """
    Add multiple characteristics by string key in one call. For each item:
      - look up CharacteristicsList by `characteristic_key` (case-insensitive)
      - if missing, create a new entry (with optional unit_of_measurement)
      - then attach to product via ProductCharacteristic

    Used by the AI product auto-fill flow where Claude returns characteristic
    names (not ids), and we need a single round-trip to insert everything.

    Body: { items: [{ key: str, value: str, unit?: str }, ...] }
    Response: { success, added: [{ characteristic_id, key, value, unit }] }
    """
    body = request.json or {}
    items = body.get('items') or []
    if not isinstance(items, list):
        return jsonify({'error': 'items должен быть массивом'}), 400

    added = []
    next_sort_order = (
        db.session.query(db.func.max(ProductCharacteristic.sort_order))
        .filter(ProductCharacteristic.product_id == product_id)
        .scalar()
        or 0
    )

    for item in items:
        if not isinstance(item, dict):
            continue
        key = (item.get('key') or '').strip()
        value = (item.get('value') or '').strip()
        unit = (item.get('unit') or '').strip() or None
        if not key or not value:
            continue

        # Find or create CharacteristicsList entry (case-insensitive match)
        cl = CharacteristicsList.query.filter(
            db.func.lower(CharacteristicsList.characteristic_key) == key.lower()
        ).first()
        if not cl:
            cl = CharacteristicsList(
                characteristic_key=key,
                unit_of_measurement=unit,
            )
            db.session.add(cl)
            try:
                db.session.flush()  # need cl.id below
            except Exception:
                db.session.rollback()
                continue

        next_sort_order += 1
        char = ProductCharacteristic(
            product_id=product_id,
            key=str(cl.id),
            value=value,
            sort_order=next_sort_order,
        )
        db.session.add(char)
        added.append({
            'characteristic_id': cl.id,
            'key': cl.characteristic_key,
            'value': value,
            'unit': cl.unit_of_measurement or '',
        })

    db.session.commit()
    return jsonify({'success': True, 'added': added}), 201


@characteristics_bp.route('/<int:char_id>', methods=['PUT'])
def update_characteristic(char_id):
    char = ProductCharacteristic.query.get_or_404(char_id)
    data = request.json
    char.key = str(data['characteristic_id'])  # Обновляем ID в поле key
    char.value = data['value']
    char.sort_order = data.get('sort_order', char.sort_order)
    db.session.commit()
    return jsonify({'message': 'Characteristic updated'})


@characteristics_bp.route('/<int:char_id>', methods=['DELETE'])
def delete_characteristic(char_id):
    char = ProductCharacteristic.query.get_or_404(char_id)
    db.session.delete(char)
    db.session.commit()
    return jsonify({'message': 'Characteristic deleted'})


@characteristics_bp.route('/reorder/<int:product_id>', methods=['POST', 'OPTIONS'])
def reorder_characteristics(product_id):
    if request.method == 'OPTIONS':
        # Ответ для preflight-запроса CORS
        return '', 200

    data = request.get_json()
    
    print(f"DEBUG: Received data: {data}")  # Отладочная информация

    if not isinstance(data, list):
        return jsonify({'error': 'Invalid data format'}), 400

    for item in data:
        print(f"DEBUG: Processing item: {item}")  # Отладочная информация
        
        char_id = item.get('id')
        sort_order = item.get('sort_order')

        if char_id is None or sort_order is None:
            print(f"DEBUG: Skipping item - missing id or sort_order")
            continue

        # Убеждаемся, что char_id это число, а не объект
        if isinstance(char_id, dict):
            print(f"DEBUG: char_id is dict: {char_id}")
            char_id = char_id.get('id')
        
        if not char_id:
            print(f"DEBUG: No valid char_id found")
            continue

        print(f"DEBUG: Looking for characteristic with id={char_id}, product_id={product_id}")
        char = ProductCharacteristic.query.filter_by(id=char_id, product_id=product_id).first()
        if char:
            print(f"DEBUG: Found characteristic, updating sort_order to {sort_order}")
            char.sort_order = sort_order
        else:
            print(f"DEBUG: Characteristic not found")

    db.session.commit()
    return jsonify({'message': 'Characteristics reordered'}), 200

