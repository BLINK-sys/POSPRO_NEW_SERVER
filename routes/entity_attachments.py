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
from models.entity_attachment import (
    EntityAttachment, EntityAttachmentVersion, ENTITY_TYPES,
)
from models.deal import Deal
from models.task import Task
from models.systemuser import SystemUser


# Лимит версий на один attachment. Старше — удаляются (БД + файл).
ATTACHMENT_VERSION_LIMIT = 30


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


def _check_deal_visible(did: int):
    """
    Возвращает (deal, error_response). Если сделка не существует или
    невидима юзеру — error_response 404. Owner/can_see_all_deals видят всё,
    остальные — только creator/responsible/member.

    Юзерам без доступа отдаём 404 (а не 403) чтобы не подтверждать существование.
    """
    from routes.deals import _visible_deals_query, _current_role_and_id
    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return None, (jsonify({'error': 'Сделка не найдена'}), 404)
    return d, None


def _check_task_visible(tid: int):
    """Аналог _check_deal_visible для задач."""
    from routes.tasks import _visible_tasks_query, _current_role_and_id
    role, user_id = _current_role_and_id()
    t = _visible_tasks_query(role, user_id).filter(Task.id == tid).first()
    if not t:
        return None, (jsonify({'error': 'Задача не найдена'}), 404)
    return t, None


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

    # Заголовок (form-field) — опциональный; пусто → в UI покажется file_name.
    raw_title = (request.form.get('title') or '').strip()
    title = raw_title[:255] if raw_title else None

    att = EntityAttachment(
        entity_type=entity_type,
        entity_id=entity_id,
        file_url=_url_for_attachment(entity_type, entity_id, disk_name),
        file_name=original_name,
        file_size=size,
        mime_type=(f.mimetype or None),
        title=title,
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
    _d, err = _check_deal_visible(did)
    if err:
        return err
    return _list_attachments('deal', did)


@entity_attachments_bp.route('/admin/deals/<int:did>/attachments', methods=['POST'])
@jwt_required()
def upload_deal_attachment(did):
    err = _check_admin_or_system()
    if err:
        return err
    _d, err = _check_deal_visible(did)
    if err:
        return err
    return _upload_attachment('deal', did)


# ---- Task ----

@entity_attachments_bp.route('/admin/tasks/<int:tid>/attachments', methods=['GET'])
@jwt_required()
def list_task_attachments(tid):
    err = _check_admin_or_system()
    if err:
        return err
    _t, err = _check_task_visible(tid)
    if err:
        return err
    return _list_attachments('task', tid)


@entity_attachments_bp.route('/admin/tasks/<int:tid>/attachments', methods=['POST'])
@jwt_required()
def upload_task_attachment(tid):
    err = _check_admin_or_system()
    if err:
        return err
    _t, err = _check_task_visible(tid)
    if err:
        return err
    return _upload_attachment('task', tid)


# ============================================================================
# Delete / Download
# ============================================================================

def _check_attachment_visible(a: EntityAttachment):
    """Атачмент доступен если родительская сделка/задача видима юзеру."""
    if a.entity_type == 'deal':
        _d, err = _check_deal_visible(a.entity_id)
        return err
    if a.entity_type == 'task':
        _t, err = _check_task_visible(a.entity_id)
        return err
    return None


@entity_attachments_bp.route('/admin/attachments/<int:aid>', methods=['PUT'])
@jwt_required()
def update_attachment(aid):
    """
    Редактирование метаданных документа. Пока — только `title`. Файл на
    диске не трогается; чтобы «заменить файл» надо удалить и загрузить
    новый (сохраняет историю в timestamps).

    Body: {"title": "Договор № 42" | ""} — пустая строка сбрасывает
    заголовок (UI снова покажет file_name).
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404
    err = _check_attachment_visible(a)
    if err:
        return err

    data = request.get_json() or {}
    if 'title' in data:
        raw = data.get('title')
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            a.title = None
        else:
            a.title = str(raw).strip()[:255]

    db.session.commit()
    return jsonify({'success': True, 'attachment': a.to_dict()}), 200


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
    err = _check_attachment_visible(a)
    if err:
        return err

    # Пробуем удалить файл с диска.
    disk_path = _disk_path(a)
    if disk_path and os.path.exists(disk_path):
        try:
            os.remove(disk_path)
        except OSError as e:
            print(f'⚠️ delete_attachment: os.remove({disk_path}): {e}', flush=True)

    # Файлы версий (entity_attachment_version.disk_path) — чистим вручную
    # перед удалением записи attachment'а. Сами записи в БД уйдут
    # каскадом (ON DELETE CASCADE на FK).
    versions = EntityAttachmentVersion.query.filter_by(attachment_id=aid).all()
    for v in versions:
        if v.disk_path and os.path.exists(v.disk_path):
            try:
                os.remove(v.disk_path)
            except OSError as e:
                print(f'⚠️ delete_attachment: os.remove(version {v.disk_path}): {e}', flush=True)

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
    err = _check_attachment_visible(a)
    if err:
        return err
    disk_path = _disk_path(a)
    if not disk_path or not os.path.exists(disk_path):
        return jsonify({'error': 'Файл отсутствует на диске'}), 410

    return send_file(
        disk_path,
        as_attachment=True,
        download_name=a.file_name or 'file',
        mimetype=a.mime_type or 'application/octet-stream',
    )


# ============================================================================
# Edit-in-place: /raw endpoints для встроенного редактора документов
# ============================================================================

@entity_attachments_bp.route('/admin/attachments/<int:aid>/raw', methods=['GET'])
@jwt_required()
def get_attachment_raw(aid):
    """
    Отдать файл inline (не attachment) — чтобы фронтовый редактор
    (Univer / etc) мог загрузить его как ArrayBuffer и инициализироваться.
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404
    err = _check_attachment_visible(a)
    if err:
        return err
    disk_path = _disk_path(a)
    if not disk_path or not os.path.exists(disk_path):
        return jsonify({'error': 'Файл отсутствует на диске'}), 410

    return send_file(
        disk_path,
        as_attachment=False,
        download_name=a.file_name or 'file',
        mimetype=a.mime_type or 'application/octet-stream',
    )


@entity_attachments_bp.route('/admin/attachments/<int:aid>/raw', methods=['PUT'])
@jwt_required()
def put_attachment_raw(aid):
    """
    Перезаписать содержимое файла (тот же путь на диске, то же имя, тот же
    mime). Используется встроенным редактором документов при «Сохранить».

    Body: сырое содержимое файла (например xlsx-blob), Content-Type можно
    прислать таким же как mime у attachment — он не проверяется строго.

    Безопасность: можно только тому же редактору что вызывает GET /raw
    (та же проверка _check_attachment_visible). Расширение/mime менять
    нельзя — это бы сломало логику типа файла в UI.
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404
    err = _check_attachment_visible(a)
    if err:
        return err
    disk_path = _disk_path(a)
    if not disk_path:
        return jsonify({'error': 'Файл нельзя заменить (внешний URL)'}), 400

    data = request.get_data()
    if not data:
        return jsonify({'error': 'Пустое тело запроса'}), 400

    os.makedirs(os.path.dirname(disk_path), exist_ok=True)

    # Перед тем как перезаписать файл — делаем снимок старого содержимого
    # в entity_attachment_version (если файл реально существует и это не
    # первое сохранение после создания). Так у юзера остаётся история
    # правок, до ATTACHMENT_VERSION_LIMIT штук.
    if os.path.exists(disk_path):
        _save_version_snapshot(a, disk_path)

    # Пишем через временный .tmp и rename — чтобы читатели не поймали
    # полу-записанный файл.
    tmp = disk_path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, disk_path)

    a.file_size = len(data)
    a.uploaded_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'attachment': a.to_dict()}), 200


# ============================================================================
# Версии файла (история правок из встроенного редактора)
# ============================================================================


def _save_version_snapshot(a: EntityAttachment, current_disk_path: str) -> None:
    """
    Снимает текущий файл attachment'а в файл-версию и создаёт запись
    в entity_attachment_version. Старые версии сверх лимита удаляются.
    """
    # Создаём запись — чтобы получить id для имени файла.
    uid = _current_user_id()
    ver = EntityAttachmentVersion(
        attachment_id=a.id,
        disk_path='',  # временно, сейчас заполним после flush'а
        file_size=os.path.getsize(current_disk_path),
        saved_by=uid,
    )
    db.session.add(ver)
    db.session.flush()  # id
    ver.disk_path = f'{current_disk_path}.v{ver.id}'
    # Копируем содержимое старого файла в .v<id>.
    try:
        with open(current_disk_path, 'rb') as src, open(ver.disk_path, 'wb') as dst:
            dst.write(src.read())
    except Exception:
        # Если файл версии не удалось записать — откатываем запись,
        # не ломая основной save.
        db.session.rollback()
        return

    # Чистим лишние версии: оставляем последние ATTACHMENT_VERSION_LIMIT.
    old_versions = (
        EntityAttachmentVersion.query
        .filter_by(attachment_id=a.id)
        .order_by(EntityAttachmentVersion.saved_at.desc())
        .offset(ATTACHMENT_VERSION_LIMIT)
        .all()
    )
    for v in old_versions:
        try:
            if v.disk_path and os.path.exists(v.disk_path):
                os.remove(v.disk_path)
        except OSError:
            pass
        db.session.delete(v)


def _current_user_id() -> int | None:
    try:
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        return None


@entity_attachments_bp.route('/admin/attachments/<int:aid>/versions', methods=['GET'])
@jwt_required()
def list_attachment_versions(aid):
    """
    Список версий attachment'а (новые сверху). Отдаём id, время, автора,
    размер.
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404
    err = _check_attachment_visible(a)
    if err:
        return err
    versions = (
        EntityAttachmentVersion.query
        .filter_by(attachment_id=aid)
        .order_by(EntityAttachmentVersion.saved_at.desc())
        .all()
    )
    # Имена авторов — одним запросом.
    uids = sorted({v.saved_by for v in versions if v.saved_by})
    users = {u.id: u for u in SystemUser.query.filter(SystemUser.id.in_(uids)).all()} if uids else {}
    out = []
    for v in versions:
        u = users.get(v.saved_by) if v.saved_by else None
        name = (u.full_name or u.email) if u else None
        out.append(v.to_dict(user_name=name))
    return jsonify({'versions': out}), 200


@entity_attachments_bp.route(
    '/admin/attachments/<int:aid>/versions/<int:vid>/restore',
    methods=['POST'],
)
@jwt_required()
def restore_attachment_version(aid, vid):
    """
    Восстановить attachment из выбранной версии. Текущее содержимое
    сначала бэкапится как новая версия (чтобы юзер мог откатить восстановление
    тоже), затем файл версии копируется поверх основного.
    """
    err = _check_admin_or_system()
    if err:
        return err
    a = EntityAttachment.query.get(aid)
    if not a:
        return jsonify({'error': 'Файл не найден'}), 404
    err = _check_attachment_visible(a)
    if err:
        return err
    v = EntityAttachmentVersion.query.filter_by(id=vid, attachment_id=aid).first()
    if not v:
        return jsonify({'error': 'Версия не найдена'}), 404
    if not v.disk_path or not os.path.exists(v.disk_path):
        return jsonify({'error': 'Файл версии отсутствует на диске'}), 410
    disk_path = _disk_path(a)
    if not disk_path:
        return jsonify({'error': 'Файл нельзя заменить (внешний URL)'}), 400

    # Копируем файл версии поверх основного (через .tmp + replace).
    # Текущее содержимое в новую версию НЕ пишем: это раздувало список
    # версий лишними записями при каждом restore. Если нужно откатить
    # restore — выбирайте ту версию, которая была до него (она остаётся
    # в истории, т.к. restore читает файл версии, а не удаляет его).
    tmp = disk_path + '.tmp'
    with open(v.disk_path, 'rb') as src, open(tmp, 'wb') as dst:
        dst.write(src.read())
    os.replace(tmp, disk_path)

    a.file_size = os.path.getsize(disk_path)
    a.uploaded_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'attachment': a.to_dict()}), 200
