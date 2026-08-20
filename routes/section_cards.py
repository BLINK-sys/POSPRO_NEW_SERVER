"""
Admin CRUD для «Карточек разделов» (SectionCard).

Все эндпоинты под /api/admin/section-cards/*. Публичный агрегатор
(/api/public/section/<slug>) — отдельный роут в public_homepage_bp,
чтобы не пересекаться с админскими.
"""

import mimetypes
import os
import re
import unicodedata
from datetime import datetime
from urllib.parse import unquote, urlparse

import requests
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from extensions import db
from models.section_card import SectionCard, SectionCardCategory
from routes.products import safe_slugify


# Разрешённые расширения изображений (используются при загрузке по URL,
# когда Content-Type может быть неточным — fallback на расширение из URL).
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'}
_MAX_URL_IMAGE_BYTES = 10 * 1024 * 1024  # 10 МБ


section_cards_bp = Blueprint('section_cards', __name__)


# ── helpers ─────────────────────────────────────────────────────────


def _generate_unique_slug(name: str, card_id: int | None = None) -> str:
    base = safe_slugify(name) or 'section'
    slug = base
    n = 1
    while True:
        q = SectionCard.query.filter_by(slug=slug)
        if card_id:
            q = q.filter(SectionCard.id != card_id)
        if not q.first():
            return slug
        n += 1
        slug = f'{base}-{n}'


def _sanitize_filename(filename: str) -> str:
    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.replace(' ', '_')
    filename = re.sub(r'[^\wа-яА-ЯёЁ\.\-]', '', filename)
    return filename


def _allowed_file(filename: str) -> bool:
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower()
        in current_app.config['ALLOWED_EXTENSIONS']
    )


def _delete_uploaded_file(url: str | None) -> None:
    """Аккуратно удалить файл, если он лежит в UPLOAD_FOLDER."""
    if not url or not url.startswith('/uploads/'):
        return
    try:
        rel = url[len('/uploads/'):]
        full = os.path.join(current_app.config['UPLOAD_FOLDER'], rel)
        if os.path.exists(full):
            os.remove(full)
        folder = os.path.dirname(full)
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
    except Exception as e:
        print(f'[section_cards] Ошибка удаления файла {url}: {e}')


def _set_categories(card: SectionCard, category_ids: list[int]) -> None:
    """Пересоздать связи с категориями. Порядок = порядок в списке."""
    seen: set[int] = set()
    ordered: list[int] = []
    for cid in category_ids or []:
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            continue
        if cid_int in seen:
            continue
        seen.add(cid_int)
        ordered.append(cid_int)

    # Wipe existing (cascade=orphan)
    for old in list(card.categories):
        db.session.delete(old)
    db.session.flush()

    for i, cid in enumerate(ordered):
        db.session.add(SectionCardCategory(
            section_card_id=card.id,
            category_id=cid,
            order=i,
        ))


# ── CRUD ────────────────────────────────────────────────────────────


@section_cards_bp.route('/section-cards', methods=['GET'])
def list_section_cards():
    cards = SectionCard.query.order_by(SectionCard.order, SectionCard.id).all()
    return jsonify([c.to_dict() for c in cards])


@section_cards_bp.route('/section-cards/<int:card_id>', methods=['GET'])
def get_section_card(card_id: int):
    card = SectionCard.query.get_or_404(card_id)
    return jsonify(card.to_dict())


@section_cards_bp.route('/section-cards', methods=['POST'])
def create_section_card():
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name обязателен'}), 400

    target = (data.get('target') or 'link').strip()
    if target not in ('link', 'categories'):
        return jsonify({'error': 'target должен быть link или categories'}), 400

    # Slug: если админ передал — уважаем (после safe_slugify), иначе авто.
    raw_slug = (data.get('slug') or '').strip()
    if raw_slug:
        candidate = safe_slugify(raw_slug) or safe_slugify(name)
        # Проверить уникальность как есть, иначе приписать суффикс.
        if SectionCard.query.filter_by(slug=candidate).first():
            candidate = _generate_unique_slug(candidate)
        slug = candidate
    else:
        slug = _generate_unique_slug(name)

    max_order = db.session.query(db.func.max(SectionCard.order)).scalar()
    next_order = (max_order + 1) if max_order is not None else 0

    card = SectionCard(
        name=name,
        slug=slug,
        description=(data.get('description') or '').strip() or None,
        image_url=(data.get('image_url') or '').strip() or None,
        banner_image_url=(data.get('banner_image_url') or '').strip() or None,
        target=target,
        link_url=(data.get('link_url') or '').strip() or None,
        link_new_tab=bool(data.get('link_new_tab', False)),
        order=next_order,
        active=bool(data.get('active', True)),
    )
    db.session.add(card)
    db.session.flush()  # получить id для junction

    if target == 'categories':
        _set_categories(card, data.get('category_ids') or [])

    db.session.commit()
    return jsonify(card.to_dict()), 201


@section_cards_bp.route('/section-cards/<int:card_id>', methods=['PUT'])
def update_section_card(card_id: int):
    card = SectionCard.query.get_or_404(card_id)
    data = request.get_json(silent=True) or {}

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'name не может быть пустым'}), 400
        card.name = name

    # Slug: если пришёл — регенерим по нему, иначе оставляем.
    if 'slug' in data:
        raw_slug = (data.get('slug') or '').strip()
        if raw_slug:
            candidate = safe_slugify(raw_slug) or safe_slugify(card.name)
            if SectionCard.query.filter(
                SectionCard.slug == candidate,
                SectionCard.id != card.id,
            ).first():
                candidate = _generate_unique_slug(candidate, card_id=card.id)
            card.slug = candidate

    if 'description' in data:
        card.description = (data.get('description') or '').strip() or None

    if 'image_url' in data:
        new_url = (data.get('image_url') or '').strip() or None
        if new_url != card.image_url and card.image_url:
            _delete_uploaded_file(card.image_url)
        card.image_url = new_url

    if 'banner_image_url' in data:
        new_url = (data.get('banner_image_url') or '').strip() or None
        if new_url != card.banner_image_url and card.banner_image_url:
            _delete_uploaded_file(card.banner_image_url)
        card.banner_image_url = new_url

    if 'target' in data:
        target = (data.get('target') or 'link').strip()
        if target not in ('link', 'categories'):
            return jsonify({'error': 'target должен быть link или categories'}), 400
        card.target = target

    if 'link_url' in data:
        card.link_url = (data.get('link_url') or '').strip() or None
    if 'link_new_tab' in data:
        card.link_new_tab = bool(data.get('link_new_tab'))
    if 'active' in data:
        card.active = bool(data.get('active'))
    if 'order' in data:
        try:
            card.order = int(data.get('order'))
        except (TypeError, ValueError):
            pass

    if 'category_ids' in data:
        _set_categories(card, data.get('category_ids') or [])

    db.session.commit()
    return jsonify(card.to_dict())


@section_cards_bp.route('/section-cards/<int:card_id>', methods=['DELETE'])
def delete_section_card(card_id: int):
    card = SectionCard.query.get_or_404(card_id)

    # Удалить файлы (карточка и баннер)
    _delete_uploaded_file(card.image_url)
    _delete_uploaded_file(card.banner_image_url)

    db.session.delete(card)
    db.session.commit()
    return jsonify({'message': 'Карточка удалена'})


@section_cards_bp.route('/section-cards/reorder', methods=['POST'])
def reorder_section_cards():
    data = request.get_json(silent=True) or []
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список [{id, order}]'}), 400

    for item in data:
        card = SectionCard.query.get(item.get('id'))
        if card:
            try:
                card.order = int(item.get('order', card.order))
            except (TypeError, ValueError):
                pass
    db.session.commit()
    return jsonify({'message': 'Порядок обновлён'})


# ── Upload изображений (карточка / баннер) ──────────────────────────


def _ext_from_url_or_ctype(url: str, content_type: str | None) -> str:
    """Определить расширение файла: сначала по URL, потом по content-type."""
    parsed = urlparse(url)
    path = unquote(parsed.path or '')
    _, ext = os.path.splitext(path)
    ext = (ext or '').lower()
    if ext in _IMAGE_EXTS:
        return ext
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(';')[0].strip())
        if guessed:
            g = guessed.lower()
            # mimetypes даёт '.jpe' для jpeg — нормализуем
            if g == '.jpe':
                g = '.jpg'
            if g in _IMAGE_EXTS:
                return g
    return '.jpg'  # безопасный fallback


@section_cards_bp.route('/section-cards/<int:card_id>/upload-url', methods=['POST'])
def upload_section_card_image_from_url(card_id: int):
    """
    Загрузить изображение по внешнему URL — скачиваем на наш сервер, чтобы
    не зависеть от чужого хостинга (иначе картинка исчезнет, если её
    удалят/переименуют).

    POST JSON:
      url:  внешний URL картинки (http/https)
      kind: 'image' | 'banner'  (по умолчанию 'image')
    Возвращает { url, kind } — локальный /uploads/... URL.
    """
    card = SectionCard.query.get_or_404(card_id)

    data = request.get_json(silent=True) or {}
    src_url = (data.get('url') or '').strip()
    kind = (data.get('kind') or 'image').strip()

    if not src_url:
        return jsonify({'error': 'url обязателен'}), 400
    if kind not in ('image', 'banner'):
        return jsonify({'error': 'kind должен быть image или banner'}), 400
    if not (src_url.startswith('http://') or src_url.startswith('https://')):
        return jsonify({'error': 'URL должен начинаться с http:// или https://'}), 400

    try:
        resp = requests.get(src_url, stream=True, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        # Ограничение размера, если сервер прислал Content-Length
        try:
            declared = int(resp.headers.get('Content-Length') or 0)
        except ValueError:
            declared = 0
        if declared and declared > _MAX_URL_IMAGE_BYTES:
            return jsonify({'error': 'Файл слишком большой (>10 МБ)'}), 400

        ext = _ext_from_url_or_ctype(src_url, resp.headers.get('Content-Type'))
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        final_filename = f'{kind}_{timestamp}{ext}'
        folder = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'section-cards', str(card_id),
        )
        os.makedirs(folder, exist_ok=True)
        full_path = os.path.join(folder, final_filename)

        received = 0
        with open(full_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > _MAX_URL_IMAGE_BYTES:
                    f.close()
                    try:
                        os.remove(full_path)
                    except OSError:
                        pass
                    return jsonify({'error': 'Файл слишком большой (>10 МБ)'}), 400
                f.write(chunk)
    except requests.RequestException as e:
        return jsonify({'error': f'Не удалось скачать: {e}'}), 400

    new_url = f'/uploads/section-cards/{card_id}/{final_filename}'

    if kind == 'image':
        _delete_uploaded_file(card.image_url)
        card.image_url = new_url
    else:
        _delete_uploaded_file(card.banner_image_url)
        card.banner_image_url = new_url

    db.session.commit()
    return jsonify({'url': new_url, 'kind': kind})


@section_cards_bp.route('/section-cards/<int:card_id>/upload', methods=['POST'])
def upload_section_card_image(card_id: int):
    """
    POST multipart:
      file: файл
      kind: 'image' | 'banner'  (по умолчанию 'image')
    Возвращает { url, kind }.
    """
    card = SectionCard.query.get_or_404(card_id)

    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'Пустое имя файла'}), 400
    if not _allowed_file(file.filename):
        return jsonify({'error': 'Недопустимый тип файла'}), 400

    kind = (request.form.get('kind') or 'image').strip()
    if kind not in ('image', 'banner'):
        return jsonify({'error': 'kind должен быть image или banner'}), 400

    ext = os.path.splitext(_sanitize_filename(file.filename))[1]
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    final_filename = f'{kind}_{timestamp}{ext}'

    folder = os.path.join(
        current_app.config['UPLOAD_FOLDER'], 'section-cards', str(card_id),
    )
    os.makedirs(folder, exist_ok=True)
    file.save(os.path.join(folder, final_filename))

    new_url = f'/uploads/section-cards/{card_id}/{final_filename}'

    if kind == 'image':
        _delete_uploaded_file(card.image_url)
        card.image_url = new_url
    else:
        _delete_uploaded_file(card.banner_image_url)
        card.banner_image_url = new_url

    db.session.commit()
    return jsonify({'url': new_url, 'kind': kind})
