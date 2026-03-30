from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt
import os
import re
import uuid
from datetime import datetime

kp_logos_bp = Blueprint('kp_logos', __name__)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def _check_system_user():
    jwt_data = get_jwt()
    role = jwt_data.get('role')
    if role not in ('admin', 'system'):
        return None, None
    return jwt_data.get('sub'), role


def _get_user_logos_dir(user_id):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    return os.path.join(upload_folder, 'kp-logos', str(user_id))


def _allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


@kp_logos_bp.route('/kp-logos', methods=['GET'])
@jwt_required()
def list_logos():
    user_id, role = _check_system_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    logos_dir = _get_user_logos_dir(user_id)

    if not os.path.exists(logos_dir):
        return jsonify({'success': True, 'logos': []}), 200

    logos = []
    for filename in sorted(os.listdir(logos_dir)):
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if ext in ALLOWED_IMAGE_EXTENSIONS:
            filepath = os.path.join(logos_dir, filename)
            stat = os.stat(filepath)
            logos.append({
                'filename': filename,
                'url': f'/uploads/kp-logos/{user_id}/{filename}',
                'size': stat.st_size,
                'uploaded_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

    return jsonify({'success': True, 'logos': logos}), 200


@kp_logos_bp.route('/kp-logos/upload', methods=['POST'])
@jwt_required()
def upload_logo():
    user_id, role = _check_system_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Файл не найден'}), 400

    file = request.files['file']
    if not file.filename or not _allowed_image(file.filename):
        return jsonify({'success': False, 'message': 'Недопустимый формат файла'}), 400

    logos_dir = _get_user_logos_dir(user_id)
    os.makedirs(logos_dir, exist_ok=True)

    # Generate unique filename preserving extension
    ext = file.filename.rsplit('.', 1)[1].lower()
    # Keep original name but sanitize + add short uuid to avoid collisions
    original_name = file.filename.rsplit('.', 1)[0]
    safe_name = re.sub(r'[<>:"/\\|?*]', '', original_name).replace(' ', '_')
    safe_name = safe_name[:50]  # limit length
    unique_name = f"{safe_name}_{uuid.uuid4().hex[:6]}.{ext}"

    filepath = os.path.join(logos_dir, unique_name)
    file.save(filepath)

    url = f'/uploads/kp-logos/{user_id}/{unique_name}'

    return jsonify({
        'success': True,
        'message': 'Логотип загружен',
        'logo': {
            'filename': unique_name,
            'url': url,
            'size': os.path.getsize(filepath),
            'uploaded_at': datetime.now().isoformat(),
        }
    }), 201


@kp_logos_bp.route('/kp-logos/<filename>', methods=['DELETE'])
@jwt_required()
def delete_logo(filename):
    user_id, role = _check_system_user()
    if not user_id:
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    logos_dir = _get_user_logos_dir(user_id)
    filepath = os.path.join(logos_dir, filename)

    # Security: ensure filename doesn't escape directory
    if not os.path.abspath(filepath).startswith(os.path.abspath(logos_dir)):
        return jsonify({'success': False, 'message': 'Недопустимое имя файла'}), 400

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'message': 'Файл не найден'}), 404

    os.remove(filepath)
    return jsonify({'success': True, 'message': 'Логотип удалён'}), 200
