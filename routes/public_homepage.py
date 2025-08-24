from flask import Blueprint, jsonify

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


@public_homepage_bp.route('/public/homepage', methods=['GET'])
def get_homepage_data():
    banners = Banner.query.filter_by(active=True).order_by(Banner.order).all()
    small_banners = {b.id: b for b in SmallBanner.query.all()}
    banners_data = [{
        'id': b.id,
        'title': b.title,
        'subtitle': b.subtitle,
        'image': b.image,
        'button_text': b.button_text,
        'button_link': b.button_link,
        'show_button': b.show_button,
        'order': b.order
    } for b in banners]

    blocks = HomepageBlock.query.filter_by(active=True).order_by(HomepageBlock.order).all()
    
    # Отладочная информация
    print(f"Found {len(blocks)} active blocks")
    for block in blocks:
        print(f"Block {block.id}: {block.title} (type: {block.type})")

    # Используем правильные названия таблиц
    categories = {c.id: c for c in Category.query.all()}
    brands = {b.id: b for b in Brand.query.all()}
    benefits = {b.id: b for b in Benefit.query.all()}
    products = {p.id: p for p in Product.query.all()}
    small_banners_all = {b.id: b for b in SmallBanner.query.all()}
    
    print(f"Available items: {len(categories)} categories, {len(brands)} brands, {len(benefits)} benefits, {len(products)} products")
    print(f"Category IDs: {list(categories.keys())}")
    print(f"Brand IDs: {list(brands.keys())}")
    print(f"Benefit IDs: {list(benefits.keys())}")
    print(f"Product IDs: {list(products.keys())}")

    blocks_data = []

    for block in blocks:
        # Явно получаем элементы блока из базы данных
        block_items = HomepageBlockItem.query.filter_by(block_id=block.id).order_by(HomepageBlockItem.order).all()
        print(f"Block {block.id} has {len(block_items)} items in database")
        
        # Выводим все item_id для этого блока
        item_ids = [item.item_id for item in block_items]
        print(f"Item IDs for block {block.id}: {item_ids}")
        
        items_data = []

        for item in block_items:
            print(f"Processing item {item.id} with item_id {item.item_id} for block type {block.type}")
            
            if block.type in ['category', 'categories']:
                cat = categories.get(item.item_id)
                if cat:
                    items_data.append({
                        'id': cat.id,
                        'name': cat.name,
                        'slug': cat.slug,
                        'image_url': cat.image_url
                    })
                    print(f"Added category: {cat.name}")
                else:
                    print(f"Category with id {item.item_id} not found")
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
                    print(f"Added brand: {br.name}")
                else:
                    print(f"Brand with id {item.item_id} not found")
            elif block.type in ['benefit', 'benefits']:
                ben = benefits.get(item.item_id)
                if ben:
                    items_data.append({
                        'id': ben.id,
                        'icon': ben.icon,
                        'title': ben.title,
                        'description': ben.description
                    })
                    print(f"Added benefit: {ben.title}")
                else:
                    print(f"Benefit with id {item.item_id} not found")
            elif block.type in ['product', 'products']:
                pr = products.get(item.item_id)
                if pr:
                    first_image = ProductMedia.query.filter_by(product_id=pr.id, media_type='image') \
                        .order_by(ProductMedia.order).first()

                    status_data = None
                    if pr.status_info:
                        status_data = {
                            'id': pr.status_info.id,
                            'name': pr.status_info.name,
                            'background_color': pr.status_info.background_color,
                            'text_color': pr.status_info.text_color,
                        }

                    brand_data = None
                    if pr.brand:
                        # Ищем бренд по названию (поле brand содержит название, а не ID)
                        brand = Brand.query.filter_by(name=pr.brand).first()
                        print(f"🔍 Ищем бренд '{pr.brand}' для товара '{pr.name}' на главной странице")
                        if brand:
                            print(f"✅ Найден бренд: {brand.name} (ID: {brand.id})")
                            brand_data = {
                                'id': brand.id,
                                'name': brand.name,
                                'country': brand.country,
                                'description': brand.description,
                                'image_url': brand.image_url
                            }
                        else:
                            print(f"❌ Бренд '{pr.brand}' не найден в базе данных для товара '{pr.name}'")

                    items_data.append({
                        'id': pr.id,
                        'name': pr.name,
                        'slug': pr.slug,
                        'price': pr.price,
                        'status': status_data,
                        'brand': brand_data,
                        'quantity': pr.quantity,
                        'image_url': first_image.url if first_image else None
                    })
                    print(f"Added product: {pr.name}")
                else:
                    print(f"Product with id {item.item_id} not found")
            elif block.type in ['small_banner', 'small_banners', 'info_cards']:
                sb = small_banners_all.get(item.item_id)
                if sb:
                    items_data.append({
                        'id': sb.id,
                        'title': sb.title,
                        'description': sb.description,
                        'image_url': sb.image_url,
                        'card_bg_color': sb.card_bg_color,
                        'show_button': sb.show_button,
                        'button_text': sb.button_text,
                        'button_text_color': sb.button_text_color,
                        'button_bg_color': sb.button_bg_color,
                        'button_link': sb.button_link
                    })
                    print(f"Added small banner: {sb.title}")
                else:
                    print(f"Small banner with id {item.item_id} not found")

        print(f"Final items count for block {block.id}: {len(items_data)}")
        
        blocks_data.append({
            'id': block.id,
            'type': block.type,
            'title': block.title,
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


@public_homepage_bp.route('/public/category/<string:slug>', methods=['GET'])
def get_category_with_children_and_products(slug):
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

    # 🔹 Товары в текущей категории
    products = Product.query.filter_by(category_id=category.id, is_visible=True).all()
    products_data = []
    
    # 🔹 Собираем уникальные бренды из товаров
    unique_brands = set()
    for p in products:
        first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
            .order_by(ProductMedia.order).first()

        status_data = None
        if p.status_info:
            status_data = {
                'id': p.status_info.id,
                'name': p.status_info.name,
                'background_color': p.status_info.background_color,
                'text_color': p.status_info.text_color,
            }

        # 🔹 Получить объект бренда по названию
        brand_data = None
        if p.brand:
            # Ищем бренд по названию (поле brand содержит название, а не ID)
            brand = Brand.query.filter_by(name=p.brand).first()
            print(f"🔍 Ищем бренд '{p.brand}' для товара '{p.name}'")
            if brand:
                print(f"✅ Найден бренд: {brand.name} (ID: {brand.id})")
                brand_data = {
                    'id': brand.id,
                    'name': brand.name,
                    'country': brand.country,
                    'description': brand.description,
                    'image_url': brand.image_url
                }
                # Добавляем бренд в уникальный список
                unique_brands.add(brand.id)
            else:
                print(f"❌ Бренд '{p.brand}' не найден в базе данных")

        products_data.append({
            'id': p.id,
            'name': p.name,
            'slug': p.slug,
            'price': p.price,
            'status': status_data,
            'brand': brand_data,
            'quantity': p.quantity,
            'image_url': first_image.url if first_image else None
        })

    # 🔹 Формируем список уникальных брендов
    brands_data = []
    print(f"📋 Уникальные ID брендов: {unique_brands}")
    for brand_id in unique_brands:
        brand = Brand.query.get(brand_id)
        if brand:
            print(f"✅ Добавляем бренд в список: {brand.name}")
            brands_data.append({
                'id': brand.id,
                'name': brand.name,
                'country': brand.country,
                'description': brand.description,
                'image_url': brand.image_url
            })
        else:
            print(f"❌ Бренд с ID {brand_id} не найден")
    
    print(f"📊 Итого брендов в ответе: {len(brands_data)}")

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
        'brands': brands_data
    })
