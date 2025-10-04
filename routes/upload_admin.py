# routes/upload_admin.py

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import os
import re
import unicodedata
from datetime import datetime
from extensions import db
from models.banner import Banner

upload_admin_bp = Blueprint('upload_admin', __name__)


def sanitize_filename(filename):
    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.replace(' ', '_')
    filename = re.sub(r'[^\wа-яА-ЯёЁ\.\-]', '', filename)
    return filename


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


# 🔹 Загрузка изображения
@upload_admin_bp.route('/upload-image', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400

    # Получаем ID баннера из параметров запроса
    banner_id = request.form.get('banner_id')
    if not banner_id:
        return jsonify({'error': 'ID баннера не указан'}), 400

    filename = sanitize_filename(file.filename)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    ext = os.path.splitext(filename)[1]
    final_filename = f"{timestamp}{ext}"

    # Создаем директорию для конкретного баннера
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'banners', banner_id)
    os.makedirs(folder, exist_ok=True)

    file_path = os.path.join(folder, final_filename)
    file.save(file_path)

    # Сохраняем URL изображения в базу данных
    image_url = f'/uploads/banners/{banner_id}/{final_filename}'
    
    try:
        banner = Banner.query.get(banner_id)
        if banner:
            # Удаляем старое изображение, если есть
            if banner.image and banner.image.startswith('/uploads/'):
                try:
                    old_file = os.path.join(current_app.config['UPLOAD_FOLDER'], banner.image[9:])  # Remove '/uploads/' prefix
                    if os.path.exists(old_file):
                        os.remove(old_file)
                except Exception as e:
                    print(f"Ошибка удаления старого изображения баннера: {e}")
            
            banner.image = image_url
            db.session.commit()
            print(f"Banner image URL saved to database: {image_url}")
        else:
            print(f"Banner with ID {banner_id} not found")
    except Exception as e:
        print(f"Error saving banner image to database: {e}")
        db.session.rollback()

    return jsonify({
        'message': 'Image uploaded',
        'url': image_url
    })


# 🔹 Удаление изображения
@upload_admin_bp.route('/images/<string:filename>', methods=['DELETE'])
def delete_image(filename):
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'banners')
    file_path = os.path.join(folder, sanitize_filename(filename))

    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    try:
        os.remove(file_path)
        return jsonify({'message': 'Image deleted'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
