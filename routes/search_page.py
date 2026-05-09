"""
Конфигурация страницы поиска (`/search`).

Публичный GET отдаёт фронту:
  - settings: { categories_enabled, brands_enabled }
  - categories: [{id, name, slug, image_url}]
  - brands: [{id, name, image_url}]

Если оба таба выключены, фронт прячет панельку целиком (юзер видит
просто пустой стейт со строкой поиска, как раньше).

Админские роуты — settings PUT для тоглов и replace-list PUT для самих
коллекций (по тому же шаблону что homepage_categories.py).
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models.search_page import (
    SearchPageSettings,
    SearchPageCategory,
    SearchPageBrand,
)
from models.category import Category
from models.brand import Brand

search_page_bp = Blueprint('search_page', __name__)


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _get_or_create_settings() -> SearchPageSettings:
    """Singleton-row pattern: возвращаем существующую настройку или создаём."""
    s = SearchPageSettings.query.first()
    if s is None:
        s = SearchPageSettings(categories_enabled=True, brands_enabled=True)
        db.session.add(s)
        db.session.commit()
    return s


# ─── Публичный эндпоинт ──────────────────────────────────────────────────

@search_page_bp.route('/public/search-page', methods=['GET'])
def get_public_search_page():
    """
    Всё что нужно фронту для отрисовки панели на /search:
    settings + denormalized categories/brands в нужном порядке.
    """
    settings = _get_or_create_settings()

    # Категории через JOIN — сразу с нужными полями для карточек
    cat_rows = (
        db.session.query(SearchPageCategory, Category)
        .join(Category, Category.id == SearchPageCategory.category_id)
        .order_by(SearchPageCategory.order, SearchPageCategory.id)
        .all()
    )
    categories = [{
        'id': cat.id,
        'name': cat.name,
        'slug': cat.slug,
        'image_url': cat.image_url,
    } for _, cat in cat_rows]

    brand_rows = (
        db.session.query(SearchPageBrand, Brand)
        .join(Brand, Brand.id == SearchPageBrand.brand_id)
        .order_by(SearchPageBrand.order, SearchPageBrand.id)
        .all()
    )
    brands = [{
        'id': brand.id,
        'name': brand.name,
        'image_url': brand.image_url,
    } for _, brand in brand_rows]

    return jsonify({
        'settings': settings.to_dict(),
        'categories': categories,
        'brands': brands,
    })


# ─── Админские эндпоинты — settings ─────────────────────────────────────

@search_page_bp.route('/admin/search-page/settings', methods=['GET'])
@jwt_required()
def get_settings():
    err = _check_admin_role()
    if err:
        return err
    return jsonify(_get_or_create_settings().to_dict())


@search_page_bp.route('/admin/search-page/settings', methods=['PUT'])
@jwt_required()
def update_settings():
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json() or {}
    settings = _get_or_create_settings()
    if 'categories_enabled' in data:
        settings.categories_enabled = bool(data['categories_enabled'])
    if 'brands_enabled' in data:
        settings.brands_enabled = bool(data['brands_enabled'])
    db.session.commit()
    return jsonify(settings.to_dict())


# ─── Админские эндпоинты — категории ─────────────────────────────────────

@search_page_bp.route('/admin/search-page/categories', methods=['GET'])
@jwt_required()
def get_admin_categories():
    err = _check_admin_role()
    if err:
        return err
    rows = SearchPageCategory.query.order_by(SearchPageCategory.order).all()
    return jsonify([r.category_id for r in rows])


@search_page_bp.route('/admin/search-page/categories', methods=['PUT'])
@jwt_required()
def replace_admin_categories():
    """
    Тело: список category_id в нужном порядке. Полная замена коллекции —
    тот же подход как у homepage-categories. ON DELETE CASCADE на FK к
    category защищает от мёртвых ссылок если категорию удалили в админке.
    """
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список ID категорий'}), 400

    SearchPageCategory.query.delete()
    for idx, category_id in enumerate(data):
        try:
            cid = int(category_id)
        except (TypeError, ValueError):
            continue
        # Пропускаем несуществующие категории — мягко
        if not Category.query.get(cid):
            continue
        db.session.add(SearchPageCategory(category_id=cid, order=idx))
    db.session.commit()
    return jsonify({'message': 'Категории обновлены'})


# ─── Админские эндпоинты — бренды ────────────────────────────────────────

@search_page_bp.route('/admin/search-page/brands', methods=['GET'])
@jwt_required()
def get_admin_brands():
    err = _check_admin_role()
    if err:
        return err
    rows = SearchPageBrand.query.order_by(SearchPageBrand.order).all()
    return jsonify([r.brand_id for r in rows])


@search_page_bp.route('/admin/search-page/brands', methods=['PUT'])
@jwt_required()
def replace_admin_brands():
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список ID брендов'}), 400

    SearchPageBrand.query.delete()
    for idx, brand_id in enumerate(data):
        try:
            bid = int(brand_id)
        except (TypeError, ValueError):
            continue
        if not Brand.query.get(bid):
            continue
        db.session.add(SearchPageBrand(brand_id=bid, order=idx))
    db.session.commit()
    return jsonify({'message': 'Бренды обновлены'})
