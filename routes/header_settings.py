"""
Управление конфигурацией шапки сайта (admin → Страницы → Шапка).

Модели: HeaderSettings + HeaderMenuItem + HeaderMenuItemProduct
(см. models/header_settings.py).

Публичные эндпоинты:
  GET /api/public/header
    Всё что нужно фронту для рендера шапки одним запросом:
      - strip: { enabled, text, clickable, url, open_new_tab }
      - menu_items: список [{ id, kind, name, slug, category_id? }]
        только is_active=True, отсортированный по order.

Админские (JWT admin/system):
  GET  /api/admin/header/settings              — настройки strip
  PUT  /api/admin/header/settings              — обновить strip
  GET  /api/admin/header/menu-items            — все items (для UI редактора)
  POST /api/admin/header/menu-items            — создать (category-ref или custom)
  PUT  /api/admin/header/menu-items/<id>       — обновить (name, is_active, product_ids)
  DELETE /api/admin/header/menu-items/<id>     — удалить
  POST /api/admin/header/menu-items/reorder    — переупорядочить

Кастомные разделы (kind='custom') открываются через тот же роут что и
категории — /category/<slug>. Fallback на custom-раздел встроен в
`public_homepage.get_category_with_children_and_products`.
"""

import re

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import or_

from extensions import db
from models.header_settings import (
    HeaderSettings,
    HeaderMenuItem,
    HeaderMenuItemProduct,
)
from models.category import Category
from models.product import Product
from routes.products import safe_slugify

header_settings_bp = Blueprint('header_settings', __name__)


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _get_or_create_settings() -> HeaderSettings:
    s = HeaderSettings.query.first()
    if s is None:
        s = HeaderSettings()
        db.session.add(s)
        db.session.commit()
    return s


_HEX_RE = re.compile(r'^#?[0-9A-Fa-f]{3,8}$')


def _normalize_color(v):
    """Валидация hex-цвета. Пусто/невалид → None; иначе строка `#RRGGBB`
    (без изменения формата, только с ведущим `#`)."""
    if not v: return None
    s = str(v).strip()
    if not s: return None
    if not _HEX_RE.match(s): return None
    return s if s.startswith('#') else f'#{s}'


def _apply_style_fields(item: HeaderMenuItem, data: dict) -> None:
    """Обновляет стилевые поля кнопки из payload, если они есть."""
    if 'border_enabled' in data:
        item.border_enabled = bool(data['border_enabled'])
    if 'border_color' in data:
        item.border_color = _normalize_color(data['border_color'])
    if 'bg_color' in data:
        item.bg_color = _normalize_color(data['bg_color'])
    if 'text_color' in data:
        item.text_color = _normalize_color(data['text_color'])


def _ensure_unique_custom_slug(base_name: str, item_id: int | None = None) -> str:
    """
    Строит slug из base_name, добавляет -2, -3… пока не станет уникальным
    среди custom-разделов И не пересечётся со slug'ами реальных категорий.
    Категории — отдельная таблица, поэтому UNIQUE constraint в БД её не
    ловит, проверяем в коде.
    """
    base = safe_slugify(base_name) or 'section'
    slug = base
    counter = 1
    while True:
        q1 = HeaderMenuItem.query.filter_by(custom_slug=slug)
        if item_id is not None:
            q1 = q1.filter(HeaderMenuItem.id != item_id)
        clashes_custom = q1.first() is not None
        clashes_category = Category.query.filter_by(slug=slug).first() is not None
        if not clashes_custom and not clashes_category:
            return slug
        counter += 1
        slug = f"{base}-{counter}"


def _serialize_menu_item(item: HeaderMenuItem, include_products: bool = False) -> dict:
    """
    Публичное представление пункта. Для kind='category' денормализуем
    name/slug из связанной Category — фронту не надо лишний JOIN.
    """
    out: dict = {
        'id': item.id,
        'kind': item.kind,
        'is_active': bool(item.is_active),
        'order': item.order,
        # Стилизация кнопки в шапке
        'border_enabled': bool(item.border_enabled),
        'border_color': item.border_color,
        'bg_color': item.bg_color,
        'text_color': item.text_color,
    }
    if item.kind == 'category':
        cat = Category.query.get(item.category_id) if item.category_id else None
        out['category_id'] = item.category_id
        out['name'] = cat.name if cat else '(категория удалена)'
        out['slug'] = cat.slug if cat else None
    else:
        out['name'] = item.custom_name or ''
        out['slug'] = item.custom_slug or None
    if include_products:
        out['product_ids'] = [p.product_id for p in item.products]
    return out


# ─── Публичный эндпоинт ──────────────────────────────────────────────────

@header_settings_bp.route('/public/header', methods=['GET'])
def get_public_header():
    settings = _get_or_create_settings()

    items = (
        HeaderMenuItem.query
        .filter_by(is_active=True)
        .order_by(HeaderMenuItem.order, HeaderMenuItem.id)
        .all()
    )

    # Отфильтровываем: category-ref на удалённую категорию, custom без slug
    menu_items = []
    for it in items:
        serialized = _serialize_menu_item(it)
        if not serialized.get('slug'):
            continue
        menu_items.append(serialized)

    return jsonify({
        'strip': settings.to_dict(),
        'menu_items': menu_items,
    })


# ─── Админ: strip settings ────────────────────────────────────────────────

@header_settings_bp.route('/admin/header/settings', methods=['GET'])
@jwt_required()
def admin_get_settings():
    err = _check_admin_role()
    if err:
        return err
    return jsonify(_get_or_create_settings().to_dict())


@header_settings_bp.route('/admin/header/settings', methods=['PUT'])
@jwt_required()
def admin_update_settings():
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json() or {}
    settings = _get_or_create_settings()
    if 'strip_enabled' in data:
        settings.strip_enabled = bool(data['strip_enabled'])
    if 'strip_text' in data:
        settings.strip_text = (data['strip_text'] or '').strip()[:500]
    if 'strip_clickable' in data:
        settings.strip_clickable = bool(data['strip_clickable'])
    if 'strip_url' in data:
        settings.strip_url = (data['strip_url'] or '').strip()[:500]
    if 'strip_open_new_tab' in data:
        settings.strip_open_new_tab = bool(data['strip_open_new_tab'])
    db.session.commit()
    return jsonify(settings.to_dict())


# ─── Админ: menu items ────────────────────────────────────────────────────

@header_settings_bp.route('/admin/header/menu-items', methods=['GET'])
@jwt_required()
def admin_list_menu_items():
    err = _check_admin_role()
    if err:
        return err
    items = (
        HeaderMenuItem.query
        .order_by(HeaderMenuItem.order, HeaderMenuItem.id)
        .all()
    )
    return jsonify([_serialize_menu_item(it, include_products=True) for it in items])


@header_settings_bp.route('/admin/header/menu-items', methods=['POST'])
@jwt_required()
def admin_create_menu_item():
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json() or {}
    kind = (data.get('kind') or '').strip()
    if kind not in ('category', 'custom'):
        return jsonify({'error': 'kind должен быть "category" или "custom"'}), 400

    # Вычисляем следующий order (в конец списка)
    max_order = db.session.query(db.func.max(HeaderMenuItem.order)).scalar() or 0

    item = HeaderMenuItem(
        kind=kind,
        is_active=bool(data.get('is_active', True)),
        order=max_order + 1,
    )

    if kind == 'category':
        cat_id = data.get('category_id')
        if not cat_id or not Category.query.get(cat_id):
            return jsonify({'error': 'category_id не найден'}), 400
        item.category_id = int(cat_id)
    else:  # custom
        name = (data.get('custom_name') or '').strip()
        if not name:
            return jsonify({'error': 'custom_name обязательно для custom-раздела'}), 400
        item.custom_name = name[:200]
        item.custom_slug = _ensure_unique_custom_slug(name)

    _apply_style_fields(item, data)

    db.session.add(item)
    db.session.flush()  # получаем item.id

    # Товары (только для custom)
    if kind == 'custom':
        product_ids = data.get('product_ids') or []
        _replace_menu_item_products(item.id, product_ids)

    db.session.commit()
    return jsonify(_serialize_menu_item(item, include_products=True))


@header_settings_bp.route('/admin/header/menu-items/<int:item_id>', methods=['PUT'])
@jwt_required()
def admin_update_menu_item(item_id):
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json() or {}
    item = HeaderMenuItem.query.get_or_404(item_id)

    if 'is_active' in data:
        item.is_active = bool(data['is_active'])

    if item.kind == 'custom':
        if 'custom_name' in data:
            name = (data['custom_name'] or '').strip()
            if not name:
                return jsonify({'error': 'custom_name не может быть пустым'}), 400
            if name != item.custom_name:
                item.custom_name = name[:200]
                # Регенерируем slug только если имя реально изменилось
                item.custom_slug = _ensure_unique_custom_slug(name, item_id=item.id)
        if 'product_ids' in data:
            _replace_menu_item_products(item.id, data['product_ids'] or [])
    else:  # category
        if 'category_id' in data:
            cat_id = data.get('category_id')
            if not cat_id or not Category.query.get(cat_id):
                return jsonify({'error': 'category_id не найден'}), 400
            item.category_id = int(cat_id)

    _apply_style_fields(item, data)

    db.session.commit()
    return jsonify(_serialize_menu_item(item, include_products=True))


@header_settings_bp.route('/admin/header/menu-items/<int:item_id>', methods=['DELETE'])
@jwt_required()
def admin_delete_menu_item(item_id):
    err = _check_admin_role()
    if err:
        return err
    item = HeaderMenuItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Пункт удалён'})


@header_settings_bp.route('/admin/header/menu-items/reorder', methods=['POST'])
@jwt_required()
def admin_reorder_menu_items():
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список ID в новом порядке'}), 400

    items = {it.id: it for it in HeaderMenuItem.query.all()}
    for idx, item_id in enumerate(data):
        try:
            iid = int(item_id)
        except (TypeError, ValueError):
            continue
        it = items.get(iid)
        if it is not None:
            it.order = idx
    db.session.commit()
    return jsonify({'message': 'Порядок обновлён'})


def _replace_menu_item_products(item_id: int, product_ids: list) -> None:
    """
    Полная замена списка товаров custom-раздела. order = позиция в списке
    (drag-and-drop на фронте сам передаёт нужный порядок).
    """
    HeaderMenuItemProduct.query.filter_by(menu_item_id=item_id).delete()
    for idx, pid in enumerate(product_ids):
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if not Product.query.get(pid_int):
            continue
        db.session.add(HeaderMenuItemProduct(
            menu_item_id=item_id,
            product_id=pid_int,
            order=idx,
        ))
