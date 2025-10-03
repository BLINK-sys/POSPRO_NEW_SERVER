from flask import Blueprint, request, jsonify
from extensions import db
from models.small_banner_card import SmallBanner
import os
import uuid
from werkzeug.utils import secure_filename

small_banner_bp = Blueprint('small_banner_bp', __name__)


@small_banner_bp.route('/small-banners', methods=['GET'])
def get_all_small_banners():
    banners = SmallBanner.query.order_by(SmallBanner.id.desc()).all()
    return jsonify([
        {
            'id': b.id,
            'title': b.title,
            'description': b.description,
            'image_url': b.image_url,
            'background_image_url': b.background_image_url,
            'title_text_color': b.title_text_color,
            'description_text_color': b.description_text_color,
            'button_text': b.button_text,
            'button_text_color': b.button_text_color,
            'button_bg_color': b.button_bg_color,
            'button_link': b.button_link,
            'card_bg_color': b.card_bg_color,
            'show_button': b.show_button
        } for b in banners
    ])


@small_banner_bp.route('/small-banners', methods=['POST'])
def create_small_banner():
    data = request.json
    banner = SmallBanner(**data)
    db.session.add(banner)
    db.session.commit()
    return jsonify({'message': 'Карточка создана', 'id': banner.id})


@small_banner_bp.route('/small-banners/<int:id>', methods=['PATCH'])
def update_small_banner(id):
    banner = SmallBanner.query.get_or_404(id)
    for key, value in request.json.items():
        setattr(banner, key, value)
    db.session.commit()
    return jsonify({'message': 'Карточка обновлена'})


@small_banner_bp.route('/small-banners/<int:id>', methods=['DELETE'])
def delete_small_banner(id):
    banner = SmallBanner.query.get_or_404(id)
    db.session.delete(banner)
    db.session.commit()
    return jsonify({'message': 'Удалено'})


@small_banner_bp.route('/small-banners/upload', methods=['POST'])
def upload_small_banner_image():
    """Загрузка изображения для малого баннера"""
    print(f"🔍 Upload request received")
    print(f"📋 Files in request: {list(request.files.keys())}")
    print(f"📋 Form data: {list(request.form.keys())}")
    
    if 'file' not in request.files:
        print(f"❌ No 'file' in request.files")
        return jsonify({'error': 'Файл не найден'}), 400
    
    file = request.files['file']
    print(f"📄 File object: {file}")
    print(f"📄 File filename: {file.filename}")
    
    if file.filename == '':
        print(f"❌ Empty filename")
        return jsonify({'error': 'Файл не выбран'}), 400
    
    if file and allowed_file(file.filename):
        print(f"✅ File is valid, processing...")
        
        # Получаем ID записи из параметров запроса
        banner_id = request.form.get('banner_id')
        if not banner_id:
            print(f"❌ No banner_id provided")
            return jsonify({'error': 'ID баннера не указан'}), 400
        
        # Генерируем уникальное имя файла
        filename = secure_filename(file.filename)
        file_extension = os.path.splitext(filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Создаем директорию для конкретного баннера
        upload_dir = f'uploads/banners/small_banners/{banner_id}'
        os.makedirs(upload_dir, exist_ok=True)
        print(f"📁 Upload directory: {upload_dir}")
        
        # Сохраняем файл
        file_path = os.path.join(upload_dir, unique_filename)
        file.save(file_path)
        print(f"💾 File saved to: {file_path}")
        
        # Возвращаем относительный путь
        relative_path = f"/uploads/banners/small_banners/{banner_id}/{unique_filename}"
        print(f"✅ Upload successful: {relative_path}")
        return jsonify({
            'success': True,
            'message': 'Изображение загружено',
            'url': relative_path
        })
    
    print(f"❌ Invalid file type: {file.filename}")
    return jsonify({'error': 'Недопустимый тип файла'}), 400


@small_banner_bp.route('/small-banners/delete-image', methods=['DELETE'])
def delete_small_banner_image():
    """Удаление изображения малого баннера"""
    print(f"🔍 Delete request received")
    print(f"📋 Request method: {request.method}")
    print(f"📋 Content-Type: {request.content_type}")
    print(f"📋 Request data: {request.get_data()}")
    
    try:
        data = request.json
        print(f"📋 Parsed JSON: {data}")
    except Exception as e:
        print(f"❌ Error parsing JSON: {e}")
        return jsonify({'error': 'Неверный формат JSON'}), 400
    
    image_url = data.get('image_url') if data else None
    
    if not image_url:
        print(f"❌ No image_url in request")
        return jsonify({'error': 'URL изображения не указан'}), 400
    
    print(f"🗑️ Delete request for: {image_url}")
    
    try:
        # Извлекаем путь к файлу из URL
        if image_url.startswith('/uploads/'):
            # Создаем полный путь используя UPLOAD_FOLDER
            relative_path = image_url.lstrip('/uploads/')
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], relative_path)
            
            print(f"📁 Full file path: {file_path}")
            
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ File deleted: {file_path}")
                
                # Удаляем папку если она пуста
                folder_path = os.path.dirname(file_path)
                if os.path.exists(folder_path) and not os.listdir(folder_path):
                    os.rmdir(folder_path)
                    print(f"🗑️ Empty folder removed: {folder_path}")
                
                return jsonify({
                    'success': True,
                    'message': 'Изображение удалено'
                })
            else:
                print(f"❌ File not found: {file_path}")
                return jsonify({'error': 'Файл не найден'}), 404
        else:
            return jsonify({'error': 'Недопустимый URL изображения'}), 400
            
    except Exception as e:
        print(f"❌ Error deleting file: {e}")
        return jsonify({'error': f'Ошибка при удалении файла: {str(e)}'}), 500


def allowed_file(filename):
    """Проверяет, является ли файл допустимым изображением"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


