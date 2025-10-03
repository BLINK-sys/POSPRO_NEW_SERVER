from flask import Blueprint, request, jsonify
from extensions import db
from models.system_brand import SystemBrand
from models.brand import Brand  # предполагаем, что есть таблица с брендами

system_brands_bp = Blueprint('system_brands', __name__)


# 🔹 Получить список выбранных брендов
@system_brands_bp.route('/system-brands', methods=['GET'])
def get_system_brands():
    items = SystemBrand.query.order_by(SystemBrand.order).all()
    brand_map = {b.id: b for b in Brand.query.all()}
    result = []

    for item in items:
        brand = brand_map.get(item.brand_id)
        if brand:
            result.append({
                'id': item.id,
                'brand_id': brand.id,
                'name': brand.name,
                'image_url': brand.image_url,
                'order': item.order
            })
    return jsonify(result)


# 🔹 Добавить бренд в отображаемые
@system_brands_bp.route('/system-brands', methods=['POST'])
def add_system_brand():
    data = request.json
    brand_id = data.get('brand_id')
    if not brand_id:
        return jsonify({'error': 'brand_id обязателен'}), 400

    # Проверка на дубль
    exists = SystemBrand.query.filter_by(brand_id=brand_id).first()
    if exists:
        return jsonify({'error': 'Бренд уже добавлен'}), 400

    max_order = db.session.query(db.func.max(SystemBrand.order)).scalar() or 0
    new_item = SystemBrand(brand_id=brand_id, order=max_order + 1)
    db.session.add(new_item)
    db.session.commit()

    return jsonify({'message': 'Бренд добавлен', 'id': new_item.id}), 201


# 🔹 Удалить из отображаемых
@system_brands_bp.route('/system-brands/<int:item_id>', methods=['DELETE'])
def delete_system_brand(item_id):
    item = SystemBrand.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Бренд удалён из отображения'})


# 🔹 Обновить порядок
@system_brands_bp.route('/system-brands/reorder', methods=['POST'])
def reorder_system_brands():
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список объектов с id и order'}), 400

    for item in data:
        record = SystemBrand.query.get(item.get('id'))
        if record and 'order' in item:
            record.order = item['order']
    db.session.commit()
    return jsonify({'message': 'Порядок обновлён'})


# 🔹 Получить все бренды из системы (для выбора)
@system_brands_bp.route('/system-brands/all', methods=['GET'])
def get_all_brands():
    brands = Brand.query.order_by(Brand.name).all()
    return jsonify([{
        'id': b.id,
        'name': b.name,
        'image_url': b.image_url,
        'country': b.country,
        'description': b.description
    } for b in brands])
