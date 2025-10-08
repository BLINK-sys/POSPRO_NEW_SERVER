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
        # Получаем данные из справочника характеристик
        characteristic_info = CharacteristicsList.query.get(c.characteristic_id)
        if characteristic_info:
            result.append({
                'id': c.id,
                'characteristic_id': c.characteristic_id,
                'key': characteristic_info.characteristic_key,
                'value': c.value,
                'unit_of_measurement': characteristic_info.unit_of_measurement,
                'sort_order': c.sort_order
            })
    
    return jsonify(result)


@characteristics_bp.route('/<int:product_id>', methods=['POST'])
def add_characteristic(product_id):
    data = request.json
    char = ProductCharacteristic(
        product_id=product_id,
        characteristic_id=data['characteristic_id'],
        value=data['value'],
        sort_order=data.get('sort_order', 0)
    )
    db.session.add(char)
    db.session.commit()
    return jsonify({'message': 'Characteristic added'}), 201


@characteristics_bp.route('/<int:char_id>', methods=['PUT'])
def update_characteristic(char_id):
    char = ProductCharacteristic.query.get_or_404(char_id)
    data = request.json
    char.characteristic_id = data['characteristic_id']
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

    if not isinstance(data, list):
        return jsonify({'error': 'Invalid data format'}), 400

    for item in data:
        char_id = item.get('id')
        sort_order = item.get('sort_order')

        if char_id is None or sort_order is None:
            continue

        char = ProductCharacteristic.query.filter_by(id=char_id, product_id=product_id).first()
        if char:
            char.sort_order = sort_order

    db.session.commit()
    return jsonify({'message': 'Characteristics reordered'}), 200

