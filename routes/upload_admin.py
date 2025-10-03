# routes/upload_admin.py

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import os
import re
import unicodedata
from datetime import datetime

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

    return jsonify({
        'message': 'Image uploaded',
        'url': f'/uploads/banners/{banner_id}/{final_filename}'
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
