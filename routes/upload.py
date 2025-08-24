from flask import Blueprint, request, jsonify, current_app
from extensions import db
from models.media import ProductMedia
from models.documents import ProductDocument
from models.category import Category
from datetime import datetime
import os
import re
import unicodedata
import mimetypes

upload_bp = Blueprint('upload', __name__)


def sanitize_filename(filename):
    """Сохраняет русские и латинские буквы, цифры, _, -, ."""
    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.replace(' ', '_')
    filename = re.sub(r'[^\wа-яА-ЯёЁ\.\-]', '', filename)
    return filename


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def get_media_type_from_filename(filename):
    """Определяет тип медиа на основе расширения файла"""
    if not filename:
        return 'image'
    
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    # Видео форматы
    video_extensions = {'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'}
    if ext in video_extensions:
        return 'video'
    
    # Изображения (по умолчанию)
    return 'image'


def sync_media_from_filesystem(product_id):
    """
    Синхронизирует медиафайлы из файловой системы с базой данных.
    Создает записи в БД для файлов, которые существуют на диске, но отсутствуют в БД.
    """
    media_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id))
    
    if not os.path.exists(media_folder):
        return
    
    # Получаем список файлов в папке (исключаем папки documents и drivers)
    try:
        files = [f for f in os.listdir(media_folder) 
                if os.path.isfile(os.path.join(media_folder, f)) 
                and f not in ['documents', 'drivers']]
    except Exception as e:
        print(f"Ошибка при чтении папки медиа: {e}")
        return
    
    # Для каждого файла проверяем, есть ли запись в БД
    for filename in files:
        file_url = f'/uploads/products/{product_id}/{filename}'
        
        # Проверяем, существует ли уже запись в БД
        existing_media = ProductMedia.query.filter_by(
            product_id=product_id, 
            url=file_url
        ).first()
        
        if not existing_media:
            # Определяем тип медиа
            media_type = get_media_type_from_filename(filename)
            
            # Создаем новую запись в БД
            new_media = ProductMedia(
                product_id=product_id,
                url=file_url,
                media_type=media_type
            )
            
            try:
                db.session.add(new_media)
                db.session.commit()
                print(f"Создана запись в БД для медиафайла: {filename}")
            except Exception as e:
                print(f"Ошибка при создании записи для медиафайла {filename}: {e}")
                db.session.rollback()


def sync_documents_from_filesystem(product_id):
    """
    Синхронизирует документы из файловой системы с базой данных.
    Создает записи в БД для файлов, которые существуют на диске, но отсутствуют в БД.
    """
    documents_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id), 'documents')
    
    if not os.path.exists(documents_folder):
        return
    
    # Получаем список файлов в папке
    try:
        files = [f for f in os.listdir(documents_folder) if os.path.isfile(os.path.join(documents_folder, f))]
    except Exception as e:
        print(f"Ошибка при чтении папки документов: {e}")
        return
    
    # Для каждого файла проверяем, есть ли запись в БД
    for filename in files:
        file_url = f'/uploads/products/{product_id}/documents/{filename}'
        
        # Проверяем, существует ли уже запись в БД
        existing_doc = ProductDocument.query.filter_by(
            product_id=product_id, 
            url=file_url, 
            file_type='doc'
        ).first()
        
        if not existing_doc:
            # Определяем MIME-тип файла
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Создаем новую запись в БД
            new_doc = ProductDocument(
                product_id=product_id,
                filename=filename,
                url=file_url,
                file_type='doc',
                mime_type=mime_type
            )
            
            try:
                db.session.add(new_doc)
                db.session.commit()
                print(f"Создана запись в БД для документа: {filename}")
            except Exception as e:
                print(f"Ошибка при создании записи для документа {filename}: {e}")
                db.session.rollback()


def sync_drivers_from_filesystem(product_id):
    """
    Синхронизирует драйверы из файловой системы с базой данных.
    Создает записи в БД для файлов, которые существуют на диске, но отсутствуют в БД.
    """
    drivers_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id), 'drivers')
    
    if not os.path.exists(drivers_folder):
        return
    
    # Получаем список файлов в папке
    try:
        files = [f for f in os.listdir(drivers_folder) if os.path.isfile(os.path.join(drivers_folder, f))]
    except Exception as e:
        print(f"Ошибка при чтении папки драйверов: {e}")
        return
    
    # Для каждого файла проверяем, есть ли запись в БД
    for filename in files:
        file_url = f'/uploads/products/{product_id}/drivers/{filename}'
        
        # Проверяем, существует ли уже запись в БД
        existing_doc = ProductDocument.query.filter_by(
            product_id=product_id, 
            url=file_url, 
            file_type='driver'
        ).first()
        
        if not existing_doc:
            # Определяем MIME-тип файла
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Создаем новую запись в БД
            new_doc = ProductDocument(
                product_id=product_id,
                filename=filename,
                url=file_url,
                file_type='driver',
                mime_type=mime_type
            )
            
            try:
                db.session.add(new_doc)
                db.session.commit()
                print(f"Создана запись в БД для драйвера: {filename}")
            except Exception as e:
                print(f"Ошибка при создании записи для драйвера {filename}: {e}")
                db.session.rollback()


# 🔹 Загрузка изображения для существующей категории
@upload_bp.route('/category/<int:category_id>', methods=['POST'])
def upload_category_image(category_id):
    category = Category.query.get_or_404(category_id)

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = sanitize_filename(file.filename)

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    ext = os.path.splitext(filename)[1]
    final_filename = f"{timestamp}{ext}"

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'categories', str(category_id))
    os.makedirs(folder, exist_ok=True)

    file_path = os.path.join(folder, final_filename)
    file.save(file_path)

    # Удалить старое изображение, если есть
    if category.image_url and category.image_url.startswith('/uploads/'):
        try:
            old_file = os.path.join(current_app.root_path, category.image_url.lstrip('/'))
            if os.path.exists(old_file):
                os.remove(old_file)
        except Exception as e:
            print(f"Ошибка удаления старого изображения: {e}")

    category.image_url = f'/uploads/categories/{category_id}/{final_filename}'
    db.session.commit()

    return jsonify({
        'message': 'Image uploaded',
        'url': category.image_url
    }), 200


@upload_bp.route('/category/<int:category_id>/image', methods=['DELETE'])
def delete_category_image(category_id):
    category = Category.query.get_or_404(category_id)

    # Если изображения нет — просто вернуть успех
    if not category.image_url or not category.image_url.startswith('/uploads/'):
        return jsonify({'message': 'No image to delete'}), 200

    # Путь к файлу
    file_path = os.path.join(current_app.root_path, category.image_url.lstrip('/'))

    try:
        if os.path.exists(file_path):
            os.remove(file_path)

        # Попробуем удалить папку, если она пустая
        folder_path = os.path.dirname(file_path)
        if os.path.exists(folder_path) and not os.listdir(folder_path):
            os.rmdir(folder_path)

        # Обновить в базе
        category.image_url = None
        db.session.commit()

        return jsonify({'message': 'Image deleted successfully'}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to delete image: {str(e)}'}), 500


# 🔹 Загрузка медиафайла для товара
@upload_bp.route('/upload_product', methods=['POST'])
def upload_product_file():
    product_id = request.form.get('product_id')
    
    if 'file' not in request.files or not product_id:
        return jsonify({'error': 'No file or product_id provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = sanitize_filename(file.filename)
    
    # ✅ Автоматически определяем тип медиа на основе расширения файла
    media_type = get_media_type_from_filename(filename)
    
    # Проверяем, что файл разрешен
    if not allowed_file(filename):
        return jsonify({'error': 'File type not allowed'}), 400

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id))
    os.makedirs(folder, exist_ok=True)

    filepath = os.path.join(folder, filename)
    file.save(filepath)

    # ✅ Создаем URL и записываем в БД
    file_url = f'/uploads/products/{product_id}/{filename}'
    
    try:
        media = ProductMedia(
            product_id=product_id,
            url=file_url,
            media_type=media_type
        )
        db.session.add(media)
        db.session.commit()
        
        return jsonify({
            'message': 'File uploaded and saved to database',
            'url': file_url,
            'id': media.id,
            'media_type': media_type,
            'filename': filename
        }), 200
        
    except Exception as e:
        print(f"Ошибка при создании записи в БД: {str(e)}")
        db.session.rollback()
        
        # Удаляем загруженный файл, если не удалось создать запись в БД
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as del_e:
            print(f"Ошибка при удалении файла после неудачной записи в БД: {del_e}")
        
        return jsonify({'error': 'Failed to save file information to database'}), 500


# 🔹 Загрузка изображений товара (альтернативный эндпоинт)
@upload_bp.route('/upload_product_image', methods=['POST'])
def upload_product_image():
    return upload_product_file()


# 🔹 Загрузка видео товара (альтернативный эндпоинт)
@upload_bp.route('/upload_product_video', methods=['POST'])
def upload_product_video():
    return upload_product_file()


# 🔹 Получить медиафайлы по товару
@upload_bp.route('/media/<int:product_id>', methods=['GET'])
def get_media(product_id):
    # Сначала синхронизируем файлы с базой данных
    sync_media_from_filesystem(product_id)
    
    media = ProductMedia.query.filter_by(product_id=product_id).order_by(ProductMedia.order).all()
    return jsonify([{
        'id': m.id,
        'url': m.url,
        'media_type': m.media_type,
        'order': m.order
    } for m in media])


# 🔹 Добавить медиа по URL
@upload_bp.route('/media/<int:product_id>', methods=['POST'])
def add_media(product_id):
    data = request.json
    media = ProductMedia(
        product_id=product_id,
        url=data['url'],
        media_type=data['media_type']
    )
    db.session.add(media)
    db.session.commit()
    return jsonify({'message': 'Media added', 'id': media.id}), 201


# 🔹 Удалить медиа
@upload_bp.route('/media/<int:media_id>', methods=['DELETE'])
def delete_media(media_id):
    media = ProductMedia.query.get_or_404(media_id)

    if media.url.startswith('/uploads/'):
        try:
            filepath = os.path.join(current_app.root_path, media.url.lstrip('/'))
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"Ошибка удаления файла: {e}")

    db.session.delete(media)
    db.session.commit()
    return jsonify({'message': 'Media deleted'})


# 🔹 Перестановка порядка медиа
@upload_bp.route('/media/reorder/<int:product_id>', methods=['POST'])
def reorder_media(product_id):
    try:
        data = request.json
        print(f"Reorder media request for product {product_id}: {data}")
        
        if not isinstance(data, list):
            return jsonify({'error': 'Invalid data format'}), 400

        # Проверяем, что все медиа существуют
        all_media = ProductMedia.query.filter_by(product_id=product_id).all()
        existing_media_ids = [m.id for m in all_media]
        
        print(f"Existing media IDs for product {product_id}: {existing_media_ids}")
        print(f"Requested media IDs: {data}")
        
        for index, media_id in enumerate(data):
            if media_id not in existing_media_ids:
                print(f"Media {media_id} not found for product {product_id}")
                return jsonify({'error': f'Media {media_id} not found for product {product_id}'}), 404
                
            media = ProductMedia.query.filter_by(id=media_id, product_id=product_id).first()
            if media:
                media.order = index
                print(f"Updated media {media_id} order to {index}")
            else:
                print(f"Media {media_id} not found for product {product_id}")
                return jsonify({'error': f'Media {media_id} not found for product {product_id}'}), 404

        db.session.commit()
        print(f"Successfully reordered media for product {product_id}")
        return jsonify({'message': 'Media reordered'}), 200
        
    except Exception as e:
        print(f"Error reordering media for product {product_id}: {str(e)}")
        db.session.rollback()
        return jsonify({'error': f'Failed to reorder media: {str(e)}'}), 500


# 🔹 Получить документы и драйвера
@upload_bp.route('/documents/<int:product_id>', methods=['GET'])
def get_documents(product_id):
    # Сначала синхронизируем файлы с базой данных
    sync_documents_from_filesystem(product_id)
    
    docs = ProductDocument.query.filter_by(product_id=product_id, file_type='doc').all()
    return jsonify([{
        'id': d.id,
        'filename': d.filename,
        'url': d.url,
        'file_type': d.file_type,
        'mime_type': d.mime_type
    } for d in docs])


@upload_bp.route('/drivers/<int:product_id>', methods=['GET'])
def get_drivers(product_id):
    # Сначала синхронизируем файлы с базой данных
    sync_drivers_from_filesystem(product_id)
    
    drivers = ProductDocument.query.filter_by(product_id=product_id, file_type='driver').all()
    return jsonify([{
        'id': d.id,
        'filename': d.filename,
        'url': d.url,
        'file_type': d.file_type,
        'mime_type': d.mime_type
    } for d in drivers])


# 🔹 Добавить документы
@upload_bp.route('/documents/<int:product_id>', methods=['POST'])
def add_document(product_id):
    try:
        data = request.json
        print(f"Добавление документа для товара {product_id}: {data}")
        
        doc = ProductDocument(
            product_id=product_id,
            filename=data['filename'],
            url=data['url'],
            file_type='doc',
            mime_type=data.get('mime_type')
        )
        db.session.add(doc)
        db.session.commit()
        
        print(f"Документ добавлен в БД с ID: {doc.id}, URL: {doc.url}")
        return jsonify({'message': 'Document added', 'id': doc.id}), 201
        
    except Exception as e:
        print(f"Ошибка при добавлении документа: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to add document'}), 500


@upload_bp.route('/drivers/<int:product_id>', methods=['POST'])
def add_driver(product_id):
    try:
        data = request.json
        print(f"Добавление драйвера для товара {product_id}: {data}")
        
        doc = ProductDocument(
            product_id=product_id,
            filename=data['filename'],
            url=data['url'],
            file_type='driver',
            mime_type=data.get('mime_type')
        )
        db.session.add(doc)
        db.session.commit()
        
        print(f"Драйвер добавлен в БД с ID: {doc.id}, URL: {doc.url}")
        return jsonify({'message': 'Driver added', 'id': doc.id}), 201
        
    except Exception as e:
        print(f"Ошибка при добавлении драйвера: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to add driver'}), 500


# 🔹 Загрузка файла-документа
@upload_bp.route('/documents/upload', methods=['POST'])
def upload_document_file():
    return _handle_file_upload(request, 'documents')


@upload_bp.route('/drivers/upload', methods=['POST'])
def upload_driver_file():
    return _handle_file_upload(request, 'drivers')


def _handle_file_upload(req, folder_type):
    product_id = req.form.get('product_id')
    if 'file' not in req.files or not product_id:
        return jsonify({'error': 'No file or product_id provided'}), 400

    file = req.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = sanitize_filename(file.filename)

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id), folder_type)
    os.makedirs(folder, exist_ok=True)

    filepath = os.path.join(folder, filename)
    file.save(filepath)

    # Создаем URL для файла
    file_url = f'/uploads/products/{product_id}/{folder_type}/{filename}'
    
    # Определяем MIME-тип файла
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'application/octet-stream'
    
    # Создаем запись в базе данных
    try:
        doc = ProductDocument(
            product_id=product_id,
            filename=filename,
            url=file_url,
            file_type=folder_type.rstrip('s'),  # 'documents' -> 'doc', 'drivers' -> 'driver'
            mime_type=mime_type
        )
        db.session.add(doc)
        db.session.commit()
        
        print(f"Файл {filename} загружен и запись создана в БД с ID: {doc.id}")
        
        return jsonify({
            'message': f'{folder_type.capitalize()} uploaded successfully',
            'url': file_url,
            'id': doc.id,
            'filename': filename,
            'mime_type': mime_type
        }), 200
        
    except Exception as e:
        print(f"Ошибка при создании записи в БД: {str(e)}")
        db.session.rollback()
        
        # Удаляем загруженный файл, если не удалось создать запись в БД
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as del_e:
            print(f"Ошибка при удалении файла после неудачной записи в БД: {del_e}")
        
        return jsonify({'error': 'Failed to save file information to database'}), 500


# 🔹 Удаление документа и драйвера
@upload_bp.route('/documents/<int:doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    return _delete_document_or_driver(doc_id, 'doc')


@upload_bp.route('/drivers/<int:doc_id>', methods=['DELETE'])
def delete_driver(doc_id):
    return _delete_document_or_driver(doc_id, 'driver')


def _delete_document_or_driver(doc_id, file_type):
    doc = ProductDocument.query.filter_by(id=doc_id, file_type=file_type).first_or_404()

    if doc.url.startswith('/uploads/'):
        try:
            filepath = os.path.join(current_app.root_path, doc.url.lstrip('/'))
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"Ошибка удаления файла ({file_type}): {e}")

    db.session.delete(doc)
    db.session.commit()
    return jsonify({'message': f'{file_type.capitalize()} deleted'})


@upload_bp.route('/small-banner', methods=['POST'])
def upload_small_banner_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = sanitize_filename(file.filename)
    ext = os.path.splitext(filename)[1]
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    final_filename = f"{timestamp}{ext}"

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'banners', 'small_banners')
    os.makedirs(folder, exist_ok=True)

    filepath = os.path.join(folder, final_filename)
    file.save(filepath)

    return jsonify({
        'message': 'Image uploaded',
        'url': f'/uploads/banners/small_banners/{final_filename}'
    }), 200
