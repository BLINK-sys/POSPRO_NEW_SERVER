from flask import Blueprint, jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from sqlalchemy import func
from sqlalchemy.orm import joinedload
import math

from extensions import db
from models import ProductMedia
from models.banner import Banner
from models.category import Category
from models.benefit import Benefit
from models.brand import Brand
from models.homepage_block_title import HomepageBlockItem
from models.product import Product  # если есть
from models.homepage_block import HomepageBlock
from models.small_banner_card import SmallBanner

public_homepage_bp = Blueprint('public_homepage', __name__)


def _is_system_user():
    """Check if current request has a valid JWT for admin/system user"""
    try:
        verify_jwt_in_request(optional=True)
        claims = get_jwt()
        return claims.get('role') in ('admin', 'system')
    except Exception:
        return False


@public_homepage_bp.route('/public', methods=['GET'])
def get_public_info():
    return {"message": "Public API", "status": "ok"}


@public_homepage_bp.route('/public/sitemap-slugs', methods=['GET'])
def get_sitemap_slugs():
    """Список slug товаров и категорий для генерации sitemap на фронте."""
    show_hidden = _is_system_user()
    query = Product.query.filter_by(is_draft=False)
    if not show_hidden:
        query = query.filter_by(is_visible=True)
    product_slugs = [
        row[0] for row in
        query.with_entities(Product.slug).all()
    ]
    category_slugs = [
        row[0] for row in
        Category.query.with_entities(Category.slug).all()
    ]
    return jsonify({
        "products": product_slugs,
        "categories": category_slugs,
    })


@public_homepage_bp.route('/public/homepage', methods=['GET'])
def get_homepage_data():
    banners = Banner.query.filter_by(active=True).order_by(Banner.order).all()
    banners_data = [{
        'id': b.id,
        'title': b.title,
        'subtitle': b.subtitle,
        'image': b.image,
        'button_text': b.button_text,
        'button_link': b.button_link,
        'show_button': b.show_button,
        'open_in_new_tab': b.open_in_new_tab,
        'button_color': b.button_color,
        'button_text_color': b.button_text_color,
        'order': b.order
    } for b in banners]

    blocks = HomepageBlock.query.filter_by(active=True).order_by(HomepageBlock.order).all()

    # ✅ ОПТИМИЗАЦИЯ: Загружаем все элементы блоков одним запросом
    block_ids = [block.id for block in blocks]
    all_block_items = []
    if block_ids:
        all_block_items = HomepageBlockItem.query.filter(
            HomepageBlockItem.block_id.in_(block_ids)
        ).order_by(HomepageBlockItem.block_id, HomepageBlockItem.order).all()
    
    # Группируем элементы по block_id
    block_items_map = {}
    for item in all_block_items:
        if item.block_id not in block_items_map:
            block_items_map[item.block_id] = []
        block_items_map[item.block_id].append(item)

    # Собираем ID, которые понадобятся далее
    category_ids = set()
    brand_ids = set()
    benefit_ids = set()
    product_ids = set()
    small_banner_ids = set()

    for block in blocks:
        block_items = block_items_map.get(block.id, [])

        for item in block_items:
            if not item.item_id:
                continue

            if block.type in ['category', 'categories']:
                category_ids.add(item.item_id)
            elif block.type in ['brand', 'brands']:
                brand_ids.add(item.item_id)
            elif block.type in ['benefit', 'benefits']:
                benefit_ids.add(item.item_id)
            elif block.type in ['product', 'products']:
                product_ids.add(item.item_id)
            elif block.type in ['small_banner', 'small_banners', 'info_cards']:
                small_banner_ids.add(item.item_id)

    # Загружаем необходимые сущности одним запросом на каждый тип
    categories = {}
    if category_ids:
        categories = {
            c.id: c for c in Category.query.filter(Category.id.in_(category_ids)).all()
        }

    brands = {}
    if brand_ids:
        brands = {
            b.id: b for b in Brand.query.filter(Brand.id.in_(brand_ids)).all()
        }

    benefits = {}
    if benefit_ids:
        benefits = {
            b.id: b for b in Benefit.query.filter(Benefit.id.in_(benefit_ids)).all()
        }

    products = {}
    if product_ids:
        products = {
            p.id: p for p in Product.query.options(
                joinedload(Product.brand_info),
                joinedload(Product.status_info),
                joinedload(Product.category)
            ).filter(Product.id.in_(product_ids)).all()
        }

    # Загружаем первое изображение для каждого товара (если есть)
    product_first_images = {}
    if product_ids:
        media_items = ProductMedia.query \
            .filter(
                ProductMedia.product_id.in_(product_ids),
                ProductMedia.media_type == 'image'
            ) \
            .order_by(ProductMedia.product_id, ProductMedia.order) \
            .all()

        for media in media_items:
            if media.product_id not in product_first_images:
                product_first_images[media.product_id] = media

    small_banners_all = {}
    if small_banner_ids:
        small_banners_all = {
            b.id: b for b in SmallBanner.query.filter(SmallBanner.id.in_(small_banner_ids)).all()
        }

    blocks_data = []

    for block in blocks:
        block_items = block_items_map.get(block.id, [])
        items_data = []

        for item in block_items:
            if block.type in ['category', 'categories']:
                cat = categories.get(item.item_id)
                if cat:
                    items_data.append({
                        'id': cat.id,
                        'name': cat.name,
                        'slug': cat.slug,
                        'image_url': cat.image_url
                    })
            elif block.type in ['brand', 'brands']:
                br = brands.get(item.item_id)
                if br:
                    items_data.append({
                        'id': br.id,
                        'name': br.name,
                        'country': br.country,
                        'description': br.description,
                        'image_url': br.image_url
                    })
            elif block.type in ['benefit', 'benefits']:
                ben = benefits.get(item.item_id)
                if ben:
                    items_data.append({
                        'id': ben.id,
                        'icon': ben.icon,
                        'title': ben.title,
                        'description': ben.description
                    })
            elif block.type in ['product', 'products']:
                pr = products.get(item.item_id)
                if pr:
                    first_image = product_first_images.get(pr.id)

                    status_data = None
                    if pr.status_info:
                        status_data = {
                            'id': pr.status_info.id,
                            'name': pr.status_info.name,
                            'background_color': pr.status_info.background_color,
                            'text_color': pr.status_info.text_color,
                        }

                    brand_data = None
                    if pr.brand_id and pr.brand_info:
                        # Используем relationship для получения информации о бренде
                        brand_data = {
                            'id': pr.brand_info.id,
                            'name': pr.brand_info.name,
                            'country': pr.brand_info.country,
                            'description': pr.brand_info.description,
                            'image_url': pr.brand_info.image_url
                        }

                    # Получаем информацию о категории
                    category_data = None
                    if pr.category:
                        category_data = {
                            'id': pr.category.id,
                            'name': pr.category.name,
                            'slug': pr.category.slug,
                            'image_url': pr.category.image_url,
                            'description': pr.category.description,
                            'parent_id': pr.category.parent_id
                        }

                    items_data.append({
                        'id': pr.id,
                        'name': pr.name,
                        'slug': pr.slug,
                        'price': pr.price,
                        'wholesale_price': pr.wholesale_price,  # Оптовая цена для админов и оптовиков
                        'category_id': pr.category_id,
                        'category': category_data,
                        'status': status_data,
                        'brand_id': pr.brand_id,
                        'brand_info': brand_data,  # Используем brand_info вместо brand
                        'brand': brand_data,  # Для обратной совместимости
                        'quantity': pr.quantity,
                        'supplier_id': pr.supplier_id,
                        'supplier_name': pr.supplier.name if pr.supplier else None,
                        'image_url': first_image.url if first_image else None
                    })
            elif block.type in ['small_banner', 'small_banners', 'info_cards']:
                sb = small_banners_all.get(item.item_id)
                if sb:
                    items_data.append({
                        'id': sb.id,
                        'title': sb.title,
                        'description': sb.description,
                        'image_url': sb.image_url,
                        'background_image_url': sb.background_image_url,
                        'title_text_color': sb.title_text_color,
                        'description_text_color': sb.description_text_color,
                        'card_bg_color': sb.card_bg_color,
                        'show_button': sb.show_button,
                        'button_text': sb.button_text,
                        'button_text_color': sb.button_text_color,
                        'button_bg_color': sb.button_bg_color,
                        'button_link': sb.button_link,
                        'open_in_new_tab': sb.open_in_new_tab
                    })

        blocks_data.append({
            'id': block.id,
            'type': block.type,
            'title': block.title,
            'description': block.description,  # ✅ Добавлено поле описания
            'order': block.order,
            'carusel': block.carusel if block.type in ['category', 'categories', 'brand', 'brands', 'benefit', 'benefits', 'product', 'products',
                                                       'small_banner', 'small_banners', 'info_cards'] else False,
            'show_title': block.show_title,
            'title_align': block.title_align,
            'items': items_data
        })

    return jsonify({
        'banners': banners_data,
        'blocks': blocks_data
    })


@public_homepage_bp.route('/public/catalog/categories', methods=['GET'])
def get_catalog_categories():
    """Получить категории для каталожных панелей (с иерархией, изображениями и количеством товаров)"""
    show_hidden = _is_system_user()
    # Получаем категории: для системных пользователей — все, для остальных — только show_in_menu=True
    try:
        cat_query = Category.query
        if not show_hidden:
            cat_query = cat_query.filter_by(show_in_menu=True)
        all_categories = cat_query.order_by(Category.parent_id, Category.order).all()
    except Exception:
        all_categories = Category.query.order_by(Category.parent_id, Category.order).all()

    category_ids = [c.id for c in all_categories]
    product_counts = {}

    if category_ids:
        counts_q = (
            db.session.query(Product.category_id, func.count(Product.id))
            .filter(Product.category_id.in_(category_ids))
        )
        if not show_hidden:
            counts_q = counts_q.filter(Product.is_visible.is_(True))
        counts_query = counts_q.group_by(Product.category_id).all()
        product_counts = {category_id: count for category_id, count in counts_query}

    # Создаем словарь для быстрого доступа
    categories_dict = {c.id: {
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'image_url': c.image_url,
        'description': c.description,
        'parent_id': c.parent_id,
        'order': c.order,
                        'children': [],
                        'product_count': product_counts.get(c.id, 0)
    } for c in all_categories}
    
    # Строим иерархию
    root_categories = []
    for cat in all_categories:
        cat_data = categories_dict[cat.id]
        if cat.parent_id is None:
            # Корневая категория
            root_categories.append(cat_data)
        else:
            # Вложенная категория
            parent = categories_dict.get(cat.parent_id)
            if parent:
                parent['children'].append(cat_data)
    
    # Сортируем корневые категории по order
    root_categories.sort(key=lambda x: x['order'] or 0)
    
    # Рекурсивно сортируем дочерние категории
    def sort_children(categories):
        for cat in categories:
            if cat['children']:
                cat['children'].sort(key=lambda x: x['order'] or 0)
                sort_children(cat['children'])
    
    sort_children(root_categories)

    def apply_product_counts(category):
        direct_count = product_counts.get(category['id'], 0)
        children_total = 0
        for child in category['children']:
            children_total += apply_product_counts(child)
        total_count = direct_count + children_total
        category['direct_product_count'] = direct_count
        category['product_count'] = total_count
        return total_count

    for root in root_categories:
        apply_product_counts(root)
    
    return jsonify(root_categories)


@public_homepage_bp.route('/public/category/<string:slug>', methods=['GET'])
def get_category_with_children_and_products(slug):
    show_hidden = _is_system_user()
    category = Category.query.filter_by(slug=slug).first_or_404()

    # 🔹 Вложенные подкатегории
    child_categories = Category.query.filter_by(parent_id=category.id).all()
    children_data = [{
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'image_url': c.image_url,
        'description': c.description,
        'parent_id': c.parent_id
    } for c in child_categories]

    # ✅ ПАГИНАЦИЯ: Получаем параметры пагинации и фильтрации
    page = request.args.get('page', default=1, type=int) or 1
    per_page = request.args.get('per_page', default=20, type=int) or 20
    per_page = max(1, min(per_page, 100))  # Ограничиваем до 100 товаров на страницу
    
    # Фильтры
    search_query = request.args.get('search', default='', type=str).strip()
    brand_filter = request.args.get('brand', default=None, type=str)
    sort_by = request.args.get('sort', default='name', type=str)

    # ✅ ОПТИМИЗАЦИЯ: Базовый запрос с relationships
    query = Product.query.options(
        joinedload(Product.brand_info),
        joinedload(Product.status_info),
        joinedload(Product.category)
    ).filter_by(category_id=category.id)
    if not show_hidden:
        query = query.filter(Product.is_visible == True)

    # Применяем фильтр по поиску
    if search_query:
        query = query.filter(
            Product.name.ilike(f'%{search_query}%')
        )
    
    # Применяем фильтр по бренду
    if brand_filter and brand_filter != 'all':
        # Пытаемся найти бренд по имени
        brand_obj = Brand.query.filter_by(name=brand_filter).first()
        if brand_obj:
            query = query.filter(Product.brand_id == brand_obj.id)
    
    # Применяем сортировку
    if sort_by == 'name':
        query = query.order_by(Product.name.asc())
    elif sort_by == 'price_asc':
        query = query.order_by(Product.price.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.name.asc())
    
    # Получаем общее количество товаров (до пагинации)
    total_count = query.count()
    total_pages = math.ceil(total_count / per_page) if total_count else 0
    
    # Корректируем номер страницы
    if total_pages and page > total_pages:
        page = total_pages
    if page < 1:
        page = 1
    
    # ✅ ПАГИНАЦИЯ: Применяем пагинацию
    products = query.offset((page - 1) * per_page).limit(per_page).all()
    
    # ✅ ОПТИМИЗАЦИЯ: Загружаем изображения одним запросом только для товаров на странице
    product_ids = [p.id for p in products]
    media_items = []
    if product_ids:
        media_items = ProductMedia.query \
            .filter(
                ProductMedia.product_id.in_(product_ids),
                ProductMedia.media_type == 'image'
            ) \
            .order_by(ProductMedia.product_id, ProductMedia.order) \
            .all()
    
    # Создаем словарь {product_id: first_image}
    product_images = {}
    for media in media_items:
        if media.product_id not in product_images:
            product_images[media.product_id] = media
    
    # ✅ ОПТИМИЗАЦИЯ: Для получения всех уникальных брендов категории делаем отдельный запрос
    # (не только из товаров на текущей странице, а из всех товаров категории)
    brands_query = Product.query.filter_by(category_id=category.id)
    if not show_hidden:
        brands_query = brands_query.filter(Product.is_visible == True)
    all_category_products = brands_query.with_entities(Product.brand_id).distinct().all()
    
    brand_ids = [p.brand_id for p in all_category_products if p.brand_id]
    all_brands = {}
    if brand_ids:
        brands_list = Brand.query.filter(Brand.id.in_(brand_ids)).all()
        all_brands = {b.id: {
            'id': b.id,
            'name': b.name,
            'country': b.country,
            'description': b.description,
            'image_url': b.image_url
        } for b in brands_list}
    
    # ✅ ОПТИМИЗАЦИЯ: Собираем данные товаров на странице
    unique_brands = {}
    products_data = []
    
    for p in products:
        first_image = product_images.get(p.id)

        status_data = None
        if p.status_info:
            status_data = {
                'id': p.status_info.id,
                'name': p.status_info.name,
                'background_color': p.status_info.background_color,
                'text_color': p.status_info.text_color,
            }

        # 🔹 Получить объект бренда через relationship
        brand_data = None
        if p.brand_id and p.brand_info:
            brand_data = {
                'id': p.brand_info.id,
                'name': p.brand_info.name,
                'country': p.brand_info.country,
                'description': p.brand_info.description,
                'image_url': p.brand_info.image_url
            }
            # Сохраняем бренд в словарь (избегаем дубликатов и дополнительных запросов)
            unique_brands[p.brand_info.id] = brand_data

        products_data.append({
            'id': p.id,
            'name': p.name,
            'slug': p.slug,
            'price': p.price,
            'wholesale_price': p.wholesale_price,  # Оптовая цена для админов и оптовиков
            'status': status_data,
            'brand_id': p.brand_id,
            'brand_info': brand_data,  # Используем brand_info вместо brand
            'brand': brand_data,  # Для обратной совместимости
            'quantity': p.quantity,
            'supplier_id': p.supplier_id,
            'supplier_name': p.supplier.name if p.supplier else None,
            'image_url': first_image.url if first_image else None
        })

    # ✅ ОПТИМИЗАЦИЯ: Возвращаем все уникальные бренды категории (не только со страницы)
    brands_data = list(all_brands.values())

    return jsonify({
        'category': {
            'id': category.id,
            'name': category.name,
            'slug': category.slug,
            'image_url': category.image_url,
            'description': category.description,
            'parent_id': category.parent_id
        },
        'children': children_data,
        'products': products_data,
        'brands': brands_data,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_count': total_count,
            'total_pages': total_pages
        }
    })
