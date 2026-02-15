from flask import Blueprint, request, jsonify, current_app
from extensions import db
from models.brand import Brand
from models.product import Product
from models.status import Status
import os
from werkzeug.utils import secure_filename
from sqlalchemy import func

bp = Blueprint('brands_statuses', __name__)


# ✅ Получить все бренды
@bp.route('/brands', methods=['GET'])
def get_brands():
    # Подсчёт видимых товаров для каждого бренда
    counts = db.session.query(
        Product.brand_id,
        func.count(Product.id).label('cnt')
    ).filter(
        Product.is_visible == True,
        Product.is_draft == False
    ).group_by(Product.brand_id).all()

    count_map = {row.brand_id: row.cnt for row in counts}

    brands = Brand.query.all()
    return jsonify([{
        'id': b.id,
        'name': b.name,
        'country': b.country,
        'description': b.description,
        'image_url': b.image_url,
        'products_count': count_map.get(b.id, 0)
    } for b in brands])


@bp.route('/brands', methods=['POST'])
def create_brand():
    data = request.json
    brand = Brand(
        name=data['name'],
        country=data.get('country', ''),
        description=data.get('description', ''),
        image_url=data.get('image_url')
    )
    db.session.add(brand)
    db.session.commit()
    return jsonify({'message': 'Brand created', 'id': brand.id})


# ✅ Создать или обновить бренд
@bp.route('/brands/<int:brand_id>', methods=['PUT'])
def update_brand(brand_id):
    data = request.json
    brand = Brand.query.get(brand_id)

    if brand:
        # Обновление
        brand.name = data['name']
        brand.country = data.get('country', '')
        brand.description = data.get('description', '')
        brand.image_url = data.get('image_url')
    else:
        # Создание без указания id (он создастся автоматически)
        brand = Brand(
            name=data['name'],
            country=data.get('country', ''),
            description=data.get('description', ''),
            image_url=data.get('image_url')
        )
        db.session.add(brand)

    db.session.commit()
    return jsonify({'message': 'Brand saved', 'id': brand.id})


# ✅ Удалить бренд
@bp.route('/brands/<int:brand_id>', methods=['DELETE'])
def delete_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    db.session.delete(brand)
    db.session.commit()
    return jsonify({'message': 'Brand deleted'})


# ✅ Загрузить изображение бренда
@bp.route('/brands/upload/<int:brand_id>', methods=['POST'])
def upload_brand_image(brand_id):
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'brands', str(brand_id))

    os.makedirs(folder, exist_ok=True)

    filepath = os.path.join(folder, filename)
    file.save(filepath)

    return jsonify({
        'url': f'/uploads/brands/{brand_id}/{filename}'
    }), 200


# ✅ Получить статусы
@bp.route('/statuses', methods=['GET'])
def get_statuses():
    statuses = Status.query.all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'background_color': s.background_color,
        'text_color': s.text_color
    } for s in statuses])


# ✅ Создать/обновить статус
@bp.route('/statuses/<int:status_id>', methods=['PUT'])
def update_status(status_id):
    data = request.json
    status = Status.query.get(status_id)

    if status:
        status.name = data['name']
        status.background_color = data.get('background_color')
        status.text_color = data.get('text_color')
    else:
        status = Status(
            name=data['name'],
            background_color=data.get('background_color'),
            text_color=data.get('text_color')
        )
        db.session.add(status)

    db.session.commit()
    return jsonify({'message': 'Status saved', 'id': status.id})


# ✅ Удалить статус
@bp.route('/statuses/<int:status_id>', methods=['DELETE'])
def delete_status(status_id):
    status = Status.query.get_or_404(status_id)
    db.session.delete(status)
    db.session.commit()
    return jsonify({'message': 'Status deleted'})
