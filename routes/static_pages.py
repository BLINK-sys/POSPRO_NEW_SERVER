"""
Статические страницы сайта (см. models/static_page.py).

Публичные:
  GET /api/public/static-page/<slug>
    Возвращает { slug, title, content, is_active }. Если страницы нет
    или is_active=False, возвращает 404 (для публичного). Админам
    /api/admin/static-page/<slug> отдаёт всегда (для редактирования
    невидимых).

Админские (JWT admin/system):
  GET /api/admin/static-page/<slug>  — читать (создаёт пустую если нет)
  PUT /api/admin/static-page/<slug>  — upsert (title, content, is_active)

Списка «все статические страницы» пока нет — админим по одной, страниц
мало. Если наберётся 5+ — добавим GET /api/admin/static-pages без slug.
"""

import os
import re
import unicodedata
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt
from werkzeug.utils import secure_filename

from extensions import db
from models.static_page import StaticPage

static_pages_bp = Blueprint('static_pages', __name__)


def _safe_name(fn: str) -> str:
    fn = unicodedata.normalize('NFKD', fn)
    fn = fn.replace(' ', '_')
    return re.sub(r'[^\wа-яА-ЯёЁ\.\-]', '', fn) or 'image'


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _get_or_create(slug: str) -> StaticPage:
    page = StaticPage.query.filter_by(slug=slug).first()
    if page is None:
        page = StaticPage(slug=slug, title='', content='', is_active=True)
        db.session.add(page)
        db.session.commit()
    return page


# ─── Публичный ────────────────────────────────────────────────────────────

@static_pages_bp.route('/public/static-page/<string:slug>', methods=['GET'])
def get_public_static_page(slug):
    page = StaticPage.query.filter_by(slug=slug, is_active=True).first()
    if page is None:
        return jsonify({'error': 'Страница не найдена'}), 404
    return jsonify(page.to_dict())


# ─── Админский ────────────────────────────────────────────────────────────

@static_pages_bp.route('/admin/static-page/<string:slug>', methods=['GET'])
@jwt_required()
def admin_get_static_page(slug):
    err = _check_admin_role()
    if err:
        return err
    page = _get_or_create(slug)
    return jsonify(page.to_dict())


@static_pages_bp.route('/admin/static-page/<string:slug>', methods=['PUT'])
@jwt_required()
def admin_update_static_page(slug):
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json() or {}
    page = _get_or_create(slug)
    if 'title' in data:
        page.title = (data['title'] or '').strip()[:200]
    if 'content' in data:
        page.content = data['content'] or ''
    if 'is_active' in data:
        page.is_active = bool(data['is_active'])
    db.session.commit()
    return jsonify(page.to_dict())


# ─── Загрузка картинок для контента страниц ─────────────────────────────
# Generic endpoint (не привязан к конкретной сущности как /upload/… для
# banner/category/product). TipTap-редактор в админке шлёт файл сюда,
# получает публичный URL и вставляет <img src="…"/> в HTML контента.

_ALLOWED_IMG_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}


@static_pages_bp.route('/admin/static-page/upload-image', methods=['POST'])
@jwt_required()
def admin_upload_image():
    err = _check_admin_role()
    if err:
        return err
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Пустое имя файла'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in _ALLOWED_IMG_EXT:
        return jsonify({'error': f'Расширение .{ext} не разрешено'}), 400

    slug = (request.form.get('slug') or 'misc').strip()[:64] or 'misc'
    slug = re.sub(r'[^a-z0-9\-]', '', slug.lower()) or 'misc'

    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    base = os.path.splitext(_safe_name(file.filename))[0][:60]
    final = f"{ts}_{base}.{ext}"

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'pages', slug)
    os.makedirs(folder, exist_ok=True)
    file.save(os.path.join(folder, final))

    return jsonify({'url': f'/uploads/pages/{slug}/{final}'})
