from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from extensions import db
from models.brand import Brand
from models.product import Product
from models.status import Status
import os
from werkzeug.utils import secure_filename
from sqlalchemy import func

bp = Blueprint('brands_statuses', __name__)


def _is_system_user():
    """Check if current request has a valid JWT for admin/system user"""
    try:
        verify_jwt_in_request(optional=True)
        claims = get_jwt()
        return claims.get('role') in ('admin', 'system')
    except Exception:
        return False


# ✅ Получить все бренды
@bp.route('/brands', methods=['GET'])
def get_brands():
    show_hidden = _is_system_user()
    # Подсчёт видимых товаров для каждого бренда
    counts_query = db.session.query(
        Product.brand_id,
        func.count(Product.id).label('cnt')
    ).filter(
        Product.is_draft == False
    )
    if not show_hidden:
        counts_query = counts_query.filter(Product.is_visible == True)
    counts = counts_query.group_by(Product.brand_id).all()

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
    from utils.external_image import is_external_image_url, download_to_uploads

    data = request.json
    requested_image = data.get('image_url')

    brand = Brand(
        name=data['name'],
        country=data.get('country', ''),
        description=data.get('description', ''),
        image_url=None,
    )
    db.session.add(brand)
    db.session.flush()  # нужен brand.id для пути сохранения картинки

    if is_external_image_url(requested_image):
        local_url, err = download_to_uploads(requested_image, f'brands/{brand.id}')
        if err:
            db.session.rollback()
            return jsonify({'error': f'Не удалось скачать картинку: {err}'}), 400
        brand.image_url = local_url
    else:
        brand.image_url = requested_image

    db.session.commit()
    return jsonify({'message': 'Brand created', 'id': brand.id})


# ✅ Создать или обновить бренд
@bp.route('/brands/<int:brand_id>', methods=['PUT'])
def update_brand(brand_id):
    from utils.external_image import is_external_image_url, download_to_uploads, remove_local_upload

    data = request.json
    brand = Brand.query.get(brand_id)
    is_new = brand is None
    requested_image = data.get('image_url')

    if is_new:
        # Создание — сначала flush чтобы получить id (нужен для пути сохранения
        # картинки), затем — если картинка внешняя — скачиваем и обновляем url.
        brand = Brand(
            name=data['name'],
            country=data.get('country', ''),
            description=data.get('description', ''),
            image_url=None,
        )
        db.session.add(brand)
        db.session.flush()
    else:
        brand.name = data['name']
        brand.country = data.get('country', '')
        brand.description = data.get('description', '')

    old_url = brand.image_url
    if is_external_image_url(requested_image):
        local_url, err = download_to_uploads(requested_image, f'brands/{brand.id}')
        if err:
            db.session.rollback()
            return jsonify({'error': f'Не удалось скачать картинку: {err}'}), 400
        if old_url and old_url.startswith('/uploads/') and old_url != local_url:
            remove_local_upload(old_url)
        brand.image_url = local_url
    else:
        if (requested_image is None or requested_image == '') and old_url and old_url.startswith('/uploads/'):
            remove_local_upload(old_url)
        brand.image_url = requested_image

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
