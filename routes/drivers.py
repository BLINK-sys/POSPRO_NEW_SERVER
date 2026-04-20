import os
import re
import mimetypes
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models import Driver, ProductDocument, Product

drivers_bp = Blueprint('drivers', __name__)

IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}


def _is_admin():
    return (get_jwt() or {}).get('role') == 'admin'


def _sanitize_filename(filename):
    filename = (filename or '').replace(' ', '_')
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    return filename or 'file'


def _usage_map():
    """Вернуть {driver_id: count} — сколько товаров используют каждый драйвер."""
    rows = (
        db.session.query(ProductDocument.driver_id, db.func.count(ProductDocument.id))
        .filter(ProductDocument.driver_id.isnot(None))
        .group_by(ProductDocument.driver_id)
        .all()
    )
    return {driver_id: count for driver_id, count in rows}


# ─── Список + деталь ──────────────────────────────────────
@drivers_bp.route('/', methods=['GET'])
@jwt_required()
def list_drivers():
    """Список драйверов (с usage_count). Админ видит все, остальные — только активные."""
    q = Driver.query.order_by(Driver.order, Driver.id)
    if not _is_admin():
        q = q.filter(Driver.is_active == True)  # noqa: E712
    drivers = q.all()
    usage = _usage_map()
    return jsonify([d.to_dict(usage_count=usage.get(d.id, 0)) for d in drivers])


@drivers_bp.route('/public', methods=['GET'])
def list_public_drivers():
    """Публичный список активных драйверов — без JWT, для каталога на сайте."""
    drivers = (
        Driver.query.filter(Driver.is_active == True)  # noqa: E712
        .order_by(Driver.order, Driver.id)
        .all()
    )
    return jsonify([
        {
            'id': d.id,
            'name': d.name,
            'url': d.url,
            'filename': d.filename,
            'mime_type': d.mime_type,
            'file_size': d.file_size,
            'image_url': d.image_url,
        }
        for d in drivers
    ])


@drivers_bp.route('/<int:driver_id>', methods=['GET'])
@jwt_required()
def get_driver(driver_id):
    d = Driver.query.get_or_404(driver_id)
    usage = _usage_map()
    return jsonify(d.to_dict(usage_count=usage.get(d.id, 0)))


@drivers_bp.route('/<int:driver_id>/products', methods=['GET'])
@jwt_required()
def get_driver_products(driver_id):
    """Список товаров, использующих этот драйвер."""
    Driver.query.get_or_404(driver_id)
    rows = (
        db.session.query(Product.id, Product.name, Product.article, Product.slug)
        .join(ProductDocument, ProductDocument.product_id == Product.id)
        .filter(ProductDocument.driver_id == driver_id)
        .distinct()
        .order_by(Product.name)
        .all()
    )
    return jsonify([
        {'id': r[0], 'name': r[1], 'article': r[2], 'slug': r[3]} for r in rows
    ])


# ─── Создание / обновление / удаление (только админ) ──────
@drivers_bp.route('/', methods=['POST'])
@jwt_required()
def create_driver():
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    name = (request.form.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Название обязательно'}), 400

    is_active_raw = request.form.get('is_active', 'true')
    is_active = str(is_active_raw).lower() in ('1', 'true', 'yes', 'да')

    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'Файл не передан'}), 400

    filename = _sanitize_filename(file.filename)

    # Сначала создаём драйвер, чтобы получить ID и папку на нём
    max_order = db.session.query(db.func.max(Driver.order)).scalar() or 0
    driver = Driver(
        name=name,
        url='',  # временно
        filename=filename,
        is_active=is_active,
        order=max_order + 1,
    )
    db.session.add(driver)
    db.session.flush()  # получим id

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'drivers', str(driver.id))
    os.makedirs(folder, exist_ok=True)

    base_path = os.path.join(folder, filename)
    if os.path.exists(base_path):
        name_part, ext_part = os.path.splitext(filename)
        i = 1
        while os.path.exists(os.path.join(folder, f'{name_part}_{i}{ext_part}')):
            i += 1
        filename = f'{name_part}_{i}{ext_part}'

    dest = os.path.join(folder, filename)
    file.save(dest)

    mime_type, _ = mimetypes.guess_type(filename)
    driver.url = f'/uploads/drivers/{driver.id}/{filename}'
    driver.filename = filename
    driver.mime_type = mime_type or 'application/octet-stream'
    driver.file_size = os.path.getsize(dest)
    db.session.commit()

    return jsonify(driver.to_dict(usage_count=0)), 201


@drivers_bp.route('/<int:driver_id>', methods=['PUT'])
@jwt_required()
def update_driver(driver_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    driver = Driver.query.get_or_404(driver_id)
    data = request.get_json() or {}

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return jsonify({'error': 'Название обязательно'}), 400
        driver.name = name
    if 'is_active' in data:
        driver.is_active = bool(data['is_active'])

    db.session.commit()
    usage = _usage_map()
    return jsonify(driver.to_dict(usage_count=usage.get(driver.id, 0)))


@drivers_bp.route('/<int:driver_id>/file', methods=['POST'])
@jwt_required()
def replace_driver_file(driver_id):
    """Перезалить файл драйвера (замена без изменения ID)."""
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    driver = Driver.query.get_or_404(driver_id)
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'Файл не передан'}), 400

    filename = _sanitize_filename(file.filename)
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'drivers', str(driver.id))
    os.makedirs(folder, exist_ok=True)

    # Удалим старый файл с диска
    if driver.url and driver.url.startswith('/uploads/'):
        old = os.path.join(current_app.config['UPLOAD_FOLDER'], driver.url[len('/uploads/'):])
        if os.path.exists(old):
            try:
                os.remove(old)
            except Exception as e:
                print(f'Не удалось удалить старый файл {old}: {e}')

    # Сохраняем новый
    dest = os.path.join(folder, filename)
    if os.path.exists(dest):
        name_part, ext_part = os.path.splitext(filename)
        i = 1
        while os.path.exists(os.path.join(folder, f'{name_part}_{i}{ext_part}')):
            i += 1
        filename = f'{name_part}_{i}{ext_part}'
        dest = os.path.join(folder, filename)

    file.save(dest)

    mime_type, _ = mimetypes.guess_type(filename)
    driver.url = f'/uploads/drivers/{driver.id}/{filename}'
    driver.filename = filename
    driver.mime_type = mime_type or 'application/octet-stream'
    driver.file_size = os.path.getsize(dest)
    db.session.commit()

    # Синхронизируем URL/filename для привязанных ProductDocument
    linked = ProductDocument.query.filter_by(driver_id=driver.id).all()
    for doc in linked:
        doc.url = driver.url
        doc.filename = driver.filename
        doc.mime_type = driver.mime_type
    db.session.commit()

    usage = _usage_map()
    return jsonify(driver.to_dict(usage_count=usage.get(driver.id, 0)))


CONTENT_TYPE_TO_EXT = {
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
}


def _save_driver_image_bytes(driver, file_bytes, orig_name, content_type=None):
    """Сохранить байты картинки в папку драйвера, обновить driver.image_url."""
    filename = _sanitize_filename(orig_name) or 'image'
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    # Если расширения нет / неверное — пробуем по Content-Type
    if ext not in IMAGE_EXTS and content_type:
        ct_main = content_type.split(';')[0].strip().lower()
        guessed = CONTENT_TYPE_TO_EXT.get(ct_main)
        if guessed:
            ext = guessed
            filename = f"{filename}.{ext}" if '.' not in filename else f"{filename.rsplit('.', 1)[0]}.{ext}"

    if ext not in IMAGE_EXTS:
        raise ValueError(
            f'Не удалось определить тип изображения. Разрешены: {", ".join(sorted(IMAGE_EXTS))}'
        )

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'drivers', str(driver.id), 'image')
    os.makedirs(folder, exist_ok=True)

    # Удалить старые картинки в папке image
    for existing in os.listdir(folder):
        try:
            os.remove(os.path.join(folder, existing))
        except Exception:
            pass

    dest = os.path.join(folder, filename)
    with open(dest, 'wb') as f:
        f.write(file_bytes)

    driver.image_url = f'/uploads/drivers/{driver.id}/image/{filename}'
    db.session.commit()


@drivers_bp.route('/<int:driver_id>/image', methods=['POST'])
@jwt_required()
def upload_driver_image(driver_id):
    """Загрузить картинку драйвера файлом (multipart)."""
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    driver = Driver.query.get_or_404(driver_id)
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'Файл не передан'}), 400

    try:
        _save_driver_image_bytes(driver, file.read(), file.filename, content_type=file.content_type)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'image_url': driver.image_url})


@drivers_bp.route('/<int:driver_id>/image-url', methods=['POST'])
@jwt_required()
def upload_driver_image_by_url(driver_id):
    """Скачать картинку по URL и сохранить локально."""
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    driver = Driver.query.get_or_404(driver_id)
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'URL обязателен'}), 400

    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=30) as resp:
            content = resp.read()
            content_type = resp.headers.get('Content-Type', '')
    except Exception as e:
        return jsonify({'error': f'Не удалось скачать: {e}'}), 400

    orig_name = os.path.basename(urlparse(url).path) or 'image'
    try:
        _save_driver_image_bytes(driver, content, orig_name, content_type=content_type)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'image_url': driver.image_url})


@drivers_bp.route('/<int:driver_id>/image', methods=['DELETE'])
@jwt_required()
def delete_driver_image(driver_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    driver = Driver.query.get_or_404(driver_id)
    if driver.image_url and driver.image_url.startswith('/uploads/'):
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], driver.image_url[len('/uploads/'):])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
    driver.image_url = None
    db.session.commit()
    return jsonify({'message': 'Картинка удалена'})


@drivers_bp.route('/<int:driver_id>', methods=['DELETE'])
@jwt_required()
def delete_driver(driver_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    driver = Driver.query.get_or_404(driver_id)

    # Удаляем связанные ProductDocument (только с driver_id == этому)
    ProductDocument.query.filter_by(driver_id=driver.id).delete()

    # Удаляем папку
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'drivers', str(driver.id))
    if os.path.isdir(folder):
        import shutil
        try:
            shutil.rmtree(folder)
        except Exception as e:
            print(f'Не удалось удалить папку {folder}: {e}')

    db.session.delete(driver)
    db.session.commit()
    return jsonify({'message': 'Удалено'})


@drivers_bp.route('/reorder', methods=['PUT'])
@jwt_required()
def reorder_drivers():
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    data = request.get_json() or {}
    ids = data.get('ids') or []
    for index, driver_id in enumerate(ids):
        d = Driver.query.get(driver_id)
        if d:
            d.order = index + 1
    db.session.commit()
    return jsonify({'message': 'Порядок обновлён'})


# ─── Привязка драйверов к товару ──────────────────────────
@drivers_bp.route('/attach/<int:product_id>', methods=['POST'])
@jwt_required()
def attach_drivers_to_product(product_id):
    """Привязать выбранные драйверы из мастер-списка к товару.
    Создаёт записи в product_document с driver_id.
    Body: {"driver_ids": [1,2,3]}
    """
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}
    ids = data.get('driver_ids') or []
    if not isinstance(ids, list):
        return jsonify({'error': 'Неверный формат данных'}), 400

    created = []
    for did in ids:
        driver = Driver.query.get(did)
        if not driver:
            continue
        # Пропустить если уже привязан
        existing = ProductDocument.query.filter_by(
            product_id=product.id, driver_id=driver.id
        ).first()
        if existing:
            continue
        doc = ProductDocument(
            product_id=product.id,
            filename=driver.filename or driver.name,
            url=driver.url,
            file_type='driver',
            mime_type=driver.mime_type,
            driver_id=driver.id,
        )
        db.session.add(doc)
        created.append(doc)
    db.session.commit()

    return jsonify({
        'attached': [{'id': d.id, 'driver_id': d.driver_id, 'url': d.url, 'filename': d.filename} for d in created]
    }), 201
