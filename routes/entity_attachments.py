"""
Прикрепления файлов к сделкам и задачам через полиморфную модель
`entity_attachment` (models/entity_attachment.py).

Endpoints:
  GET    /api/admin/deals/<id>/attachments             список файлов сделки
  POST   /api/admin/deals/<id>/attachments             upload (multipart)
  GET    /api/admin/tasks/<id>/attachments             список файлов задачи
  POST   /api/admin/tasks/<id>/attachments             upload (multipart)
  DELETE /api/admin/attachments/<aid>                  удалить (файл + запись)
  GET    /api/admin/attachments/<aid>/download         скачать файл (proxy)

Access:
  - admin/system может смотреть/удалять/загружать.
  - Проверка видимости сделки/задачи (может ли юзер их вообще видеть) —
    через `_visible_deals_query`/`_visible_tasks_query` из соответствующих
    модулей. Для сессии оставим упрощённо: любой admin/system.
    (Если юзер не имеет доступа к сделке — /admin/deals/<id> вернёт 404
    в другом месте; тут просто проверяем что сделка существует.)

Storage:
  <UPLOAD_FOLDER>/crm_attachments/<entity_type>/<entity_id>/<timestamp>_<name>

Ограничения:
  - MAX_CONTENT_LENGTH из конфига (500MB) — Flask сам режет.
  - Разрешённые расширения: те же что и глобальный ALLOWED_EXTENSIONS.
  - При upload — оригинальное имя файла сохраняется в `file_name`, а на
    диске лежит с timestamp'ом чтобы избежать коллизий.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from werkzeug.utils import secure_filename

from extensions import db
from models.entity_attachment import EntityAttachment, ENTITY_TYPES
from models.deal import Deal
from models.task import Task


entity_attachments_bp = Blueprint('entity_attachments', __name__)


ATTACHMENTS_SUBFOLDER = 'crm_attachments'


# ============================================================================
# Auth
# ============================================================================

def _check_admin_or_system():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _current_user_id() -> int | None:
    try:
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        return None


# ============================================================================
# Хелперы
# ============================================================================

def _sanitize_name(name: str) -> str:
    """
    Убираем опасные символы из имени. NFKD-нормализация склеивает
    комбинирующие символы (например ё → е). Кириллицу оставляем — это
    норм для отображения; на файловой системе с UTF-8 работает.
    """
    name = unicodedata.normalize('NFKD', name)
    name = re.sub(r'[/\\?%*:|"<>]', '_', name)
    return name.strip() or 'file'


def _allowed(filename: str) -> bool:
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config['ALLOWED_EXTENSIONS']


def _entity_folder(entity_type: str, entity_id: int) -> str:
    root = current_app.config['UPLOAD_FOLDER']
    folder = os.path.join(root, ATTACHMENTS_SUBFOLDER, entity_type, str(entity_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _entity_exists(entity_type: str, entity_id: int) -> bool:
    if entity_type == 'deal':
        return Deal.query.get(entity_id) is not None
    if entity_type == 'task':
        return Task.query.get(entity_id) is not None
    return False


def _url_for_attachment(entity_type: str, entity_id: int, disk_name: str) -> str:
    """Публичный URL под которым файл доступен через /uploads/..."""
    return f'/uploads/{ATTACHMENTS_SUBFOLDER}/{entity_type}/{entity_id}/{disk_name}'


def _disk_path(a: EntityAttachment) -> str | None:
    """
    Обратное отображение `file_url` → путь на диске. Работает для файлов
    загруженных через этот роут (URL начинается с `/uploads/<subfolder>/`).
    """
    url = a.file_url or ''
    prefix = f'/uploads/{ATTACHMENTS_SUBFOLDER}/'
    if not url.startswith(prefix):
        return None
    rel = url[len(prefix):]
    return os.path.join(
        current_app.config['UPLOAD_FOLDER'], ATTACHMENTS_SUBFOLDER, rel,
    )


# ============================================================================
# List / Upload
# ============================================================================

def _list_attachments(entity_type: str, entity_id: int):
    items = (
        EntityAttachment.query
        .filter_by(entity_type=entity_type, entity_id=entity_id)
        .order_by(EntityAttachment.uploaded_at.desc())
        .all()
    )
    return jsonify({
        'success': True,
        'attachments': [a.to_dict() for a in items],
    }), 200


def _upload_attachment(entity_type: str, entity_id: int):
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан (form-field "file")'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Пустое имя файла'}), 400
    if not _allowed(f.filename):
        return jsonify({
            'error': 'Тип файла не разрешён',
            'allowed': sorted(current_app.config['ALLOWED_EXTENSIONS']),
        }), 400

    original_name = _sanitize_name(f.filename)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    ext = os.path.splitext(original_name)[1]
    disk_name = f'{timestamp}{ext}'
    folder = _entity_folder(entity_type, entity_id)
    disk_path = os.path.join(folder, disk_name)

    f.save(disk_path)
    size = os.path.getsize(disk_path)

    att = EntityAttachment(
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=_url_for_attachment(entity_type, entity_id, disk_name),
        file_name=original_name,
        file_size=size,
        mime_type=(f.mimetype or None),
        uploaded_by=_current_user_id(),
    )
    db.session.add(att)
    db.session.commit()
    return jsonify({'success': True, 'attachment': att.to_dict()}), 201


# ---- Deal ----

@entity_attachments_bp.route('/admin/deals/<int:did>/attachments', methods=['GET'])
@jwt_required()
def list_deal_attachments(did):
    err = _check_admin_or_system()
    if err:
        return err
    if not Deal.query.get(did):
        return jsonify({'error': 'Сделка не найдена'}), 404
    return _list_attachments('deal', did)


@entity_attachments_bp.route('/admin/deals/<int:did>/attachments', methods=['POST'])
@jwt_required()
def upload_deal_attachment(did):
    err = _check_admin_or_system()
    if err:
        return err
    if not Deal.query.get(did):
        return jsonify({'error': 'Сделка не найдена'}), 404
    return _upload_attachment('deal', did)


# ---- Task ----

@entity_attachments_bp.route('/admin/tasks/<int:tid>/attachments', methods=['GET'])
@jwt_required()
def list_task_attachments(tid):
    err = _check_admin_or_system()
    if err:
        return err
    if not Task.query.get(tid):
        return jsonify({'error': 'Задача не найдена'}), 404
    return _list_attachments('task', tid)


@entity_attachments_bp.route('/admin/tasks/<int:tid>/attachments', methods=['POST'])
@jwt_required()
def upload_task_attachment(tid):
    err = _check_admin_or_system()
    if err:
        return err
    if not Task.query.get(tid):
        return jsonify({'error': 'Задача не найдена'}), 404
    return _upload_attachment('task', tid)


# ============================================================================
# Delete / Download
# ============================================================================

@entity_attachments_bp.route('/admin/attachments/<int:aid>', methods=['DELETE'])
@jwt_required()
def delete_attachment(aid):
    """
    Удаляем и запись в БД, и файл с диска. Если файл на диске отсутствует
    (был удалён вручную) — тихо удаляем запись, не падаем.
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404

    # Пробуем удалить файл с диска.
    disk_path = _disk_path(a)
    if disk_path and os.path.exists(disk_path):
        try:
            os.remove(disk_path)
        except OSError as e:
            print(f'⚠️ delete_attachment: os.remove({disk_path}): {e}', flush=True)

    db.session.delete(a)
    db.session.commit()
    return jsonify({'success': True}), 200


@entity_attachments_bp.route('/admin/attachments/<int:aid>/download', methods=['GET'])
@jwt_required()
def download_attachment(aid):
    """
    Отдаём файл как attachment (браузер предложит скачать). Используем
    оригинальное имя из `file_name`.
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404
    disk_path = _disk_path(a)
    if not disk_path or not os.path.exists(disk_path):
        return jsonify({'error': 'Файл отсутствует на диске'}), 410

    return send_file(
        disk_path,
        as_attachment=True,
        download_name=a.file_name or 'file',
        mimetype=a.mime_type or 'application/octet-stream',
    )
