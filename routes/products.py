import os
import shutil
import re
import unicodedata
from flask import Blueprint, request, jsonify, current_app
import logging
from extensions import db
from models import ProductDocument, ProductCharacteristic
from models.product import Product
from models.media import ProductMedia

products_bp = Blueprint('products', __name__)
logger = logging.getLogger(__name__)

def safe_slugify(text):
    """
    Безопасная функция для создания slug из текста.
    Работает с Python 3 и поддерживает русские символы.
    """
    if not text:
        return ''
    
    # Нормализуем Unicode символы
    text = unicodedata.normalize('NFKD', str(text))
    
    # Заменяем русские символы на латинские аналоги
    russian_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    
    # Заменяем русские символы
    for russian, latin in russian_to_latin.items():
        text = text.replace(russian, latin)
    
    # Удаляем все символы кроме букв, цифр и пробелов
    text = re.sub(r'[^\w\s-]', '', text)
    
    # Заменяем пробелы на дефисы
    text = re.sub(r'[-\s]+', '-', text)
    
    # Удаляем начальные и конечные дефисы
    text = text.strip('-')
    
    # Приводим к нижнему регистру
    return text.lower()

def generate_unique_slug(name, product_id=None):
    base_slug = safe_slugify(name)
    slug = base_slug
    counter = 1

    while True:
        query = Product.query.filter_by(slug=slug)
        if product_id:
            query = query.filter(Product.id != product_id)
        if not query.first():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


# 🔹 Создать черновик
@products_bp.route('/draft', methods=['POST'])
def create_draft_product():
    try:
        import uuid
        import time
        
        # Генерируем уникальный артикул для черновика
        unique_article = f"DRAFT-{int(time.time())}-{str(uuid.uuid4())[:8]}"
        
        draft_product = Product(
            name='',
            article=unique_article,  # Уникальный артикул
            slug='draft',
            price=0,
            wholesale_price=0,
            quantity=0,
            is_visible=False,
            country='',
            brand='',
            description='',
            status=None,
            is_draft=True,
            category_id=None
        )
        
        db.session.add(draft_product)
        db.session.commit()
        
        return jsonify({"id": draft_product.id, "article": draft_product.article}), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": str(e)}), 500


# 🔹 Удалить черновик + папку
@products_bp.route('/draft/<int:product_id>', methods=['DELETE'])
def delete_draft(product_id):
    try:
        print(f"Начало удаления черновика ID: {product_id}")
        
        product = Product.query.get_or_404(product_id)
        print(f"Товар найден: {product.name} (ID: {product.id}, is_draft: {product.is_draft})")
        
        if not product.is_draft:
            print(f"Попытка удалить не-черновик товар ID: {product_id}")
            return jsonify({'error': 'Cannot delete finalized product'}), 400

        # Удаляем связанные записи
        print(f"Удаление связанных записей для товара ID: {product_id}")
        
        media_deleted = ProductMedia.query.filter_by(product_id=product_id).delete()
        documents_deleted = ProductDocument.query.filter_by(product_id=product_id).delete()
        characteristics_deleted = ProductCharacteristic.query.filter_by(product_id=product_id).delete()
        print(f"Удалено медиа: {media_deleted}, документов: {documents_deleted}, характеристик: {characteristics_deleted}")

        # Удаляем папку с файлами
        folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id))
        try:
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                print(f"Папка {folder_path} успешно удалена.")
            else:
                print(f"Папка {folder_path} не существует.")
        except Exception as e:
            print(f"Ошибка при удалении папки {folder_path}: {e}")

        # Удаляем сам товар
        print(f"Удаление товара из БД: {product.id}")
        db.session.delete(product)
        db.session.commit()
        
        print(f"Черновик ID: {product_id} успешно удален из БД")
        return jsonify({'message': 'Draft deleted successfully'})
        
    except Exception as e:
        print(f"Ошибка при удалении черновика ID {product_id}: {str(e)}")
        db.session.rollback()
        return jsonify({'error': f'Error deleting draft: {str(e)}'}), 500


# �� Финализировать черновик
@products_bp.route('/<int:product_id>/finalize', methods=['PUT', 'POST'])
def finalize_product(product_id):
    try:
        logger.info(f"=== НАЧАЛО ФИНАЛИЗАЦИИ ТОВАРА ===")
        logger.info(f"ID товара: {product_id}")
        logger.info(f"Метод запроса: {request.method}")
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Данные запроса: {request.get_data()}")
        
        data = request.json or {}
        logger.info(f"Получены данные: {list(data.keys())}")
        logger.info(f"Полные данные: {data}")
        
        # Проверяем существование товара
        product = Product.query.get_or_404(product_id)
        logger.info(f"Товар найден: {product.name} (ID: {product.id}, is_draft: {product.is_draft})")
        
        # Проверяем, что товар является черновиком
        if not product.is_draft:
            logger.warning(f"Попытка финализировать не-черновик товар ID: {product_id}")
            return jsonify({'error': 'Товар уже финализирован'}), 400
        
        data = request.json or {}
        logger.info(f"Получены данные для финализации: {list(data.keys())}")
        
        # Валидация обязательных полей
        required_fields = ['name', 'article']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            logger.error(f"Отсутствуют обязательные поля: {missing_fields}")
            return jsonify({'error': f'Отсутствуют обязательные поля: {missing_fields}'}), 400
        
        # Сохраняем старые значения для логирования
        old_name = product.name
        old_slug = product.slug
        
        # Обновляем поля товара
        try:
            product.name = data.get('name', '')
            product.article = data.get('article', '')
            product.price = data.get('price', 0)
            product.wholesale_price = data.get('wholesale_price', 0)
            product.quantity = data.get('quantity', 0)
            
            # Простая обработка статуса и бренда
            status = data.get('status', product.status)
            brand = data.get('brand', product.brand)
            
            # Обработка 'no'
            if str(status) == 'no':
                status = None
            if str(brand) == 'no':
                brand = ''

            product.status = status            
            product.is_visible = data.get('is_visible', False)
            product.country = data.get('country', '')
            product.brand = brand
            product.description = data.get('description', '')
            product.category_id = data.get('category_id')
            
            logger.info(f"Поля товара обновлены: name='{product.name}', article='{product.article}', price={product.price}")
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении полей товара: {str(e)}")
            return jsonify({'error': 'Ошибка при обновлении данных товара'}), 500
        
        # Генерируем новый slug
        try:
            product.slug = generate_unique_slug(product.name, product.id)
            logger.info(f"Slug сгенерирован: '{old_slug}' -> '{product.slug}'")
        except Exception as e:
            logger.error(f"Ошибка при генерации slug: {str(e)}")
            return jsonify({'error': 'Ошибка при генерации URL товара'}), 500
        
        # Меняем статус на финализированный
        product.is_draft = False
        
        # Сохраняем в базу данных
        try:
            db.session.commit()
            logger.info(f"Товар успешно финализирован: ID={product.id}")
            return jsonify({'message': 'Product finalized successfully', 'id': product.id})
        except Exception as e:
            logger.error(f"Ошибка при сохранении в БД: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Ошибка при сохранении товара'}), 500
        
    except Exception as e:
        logger.error(f"Ошибка при финализации товара ID {product_id}: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Ошибка при финализации товара'}), 500


# 🔹 Получить все товары
@products_bp.route('/', methods=['GET'])
def get_products():
    products = Product.query.all()
    result = []

    for p in products:
        first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
            .order_by(ProductMedia.order).first()

        result.append({
            'id': p.id,
            'name': p.name,
            'slug': p.slug,
            'article': p.article,
            'price': p.price,
            'wholesale_price': p.wholesale_price,
            'quantity': p.quantity,
            'status': 'no' if p.status is None else str(p.status),
            'is_visible': p.is_visible,
            'country': p.country,
            'brand': 'no' if not p.brand else p.brand,
            'description': p.description,
            'category_id': p.category_id,
            'image': first_image.url if first_image else None
        })

    return jsonify(result)


# 🔹 Получить товар по slug
@products_bp.route('/<string:slug>', methods=['GET'])
def get_product_by_slug(slug):
    product = Product.query.filter_by(slug=slug).first_or_404()

    first_image = ProductMedia.query.filter_by(product_id=product.id, media_type='image') \
        .order_by(ProductMedia.order).first()

    # 🧩 Все характеристики
    characteristics = ProductCharacteristic.query.filter_by(product_id=product.id).all()
    characteristics_data = [{
        'id': c.id,
        'key': c.key,
        'value': c.value,
        'sort_order': c.sort_order
    } for c in characteristics]

    # 🖼️ Все медиафайлы
    media = ProductMedia.query.filter_by(product_id=product.id).order_by(ProductMedia.order).all()
    media_data = [{
        'id': m.id,
        'media_type': m.media_type,
        'url': m.url,
        'order': m.order
    } for m in media]

    # 📄 Документы
    documents = ProductDocument.query.filter_by(product_id=product.id, file_type='doc').all()
    documents_data = [{
        'id': d.id,
        'filename': d.filename,
        'url': d.url,
        'file_type': d.file_type,
        'mime_type': d.mime_type
    } for d in documents]

    # ⚙️ Драйверы
    drivers = ProductDocument.query.filter_by(product_id=product.id, file_type='driver').all()
    drivers_data = [{
        'id': d.id,
        'filename': d.filename,
        'url': d.url,
        'file_type': d.file_type,
        'mime_type': d.mime_type
    } for d in drivers]

    result = {
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'article': product.article,
        'price': product.price,
        'wholesale_price': product.wholesale_price,
        'quantity': product.quantity,
        'status': 'no' if product.status is None else str(product.status),
        'is_visible': product.is_visible,
        'country': product.country,
        'brand': 'no' if not product.brand else product.brand,
        'description': product.description,
        'category_id': product.category_id,
        'image': first_image.url if first_image else None,

        # Новые поля:
        'characteristics': characteristics_data,
        'media': media_data,
        'documents': documents_data,
        'drivers': drivers_data,
    }

    return jsonify(result)


# 🔹 Создать товар (не черновик)
@products_bp.route('/', methods=['POST'])
def create_product():
    try:
        logger.info("=== НАЧАЛО СОЗДАНИЯ ТОВАРА ===")
        logger.info(f"Метод запроса: {request.method}")
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Данные запроса: {request.get_data()}")
        
        data = request.json or {}
        logger.info(f"Получены данные: {list(data.keys())}")
        logger.info(f"Полные данные: {data}")

        # Простая обработка статуса и бренда
        status = data.get('status')
        brand = data.get('brand')
        
        # Обработка 'no'
        if str(status) == 'no':
            status = None
        if str(brand) == 'no':
            brand = ''

        name = data.get('name', '')
        logger.info(f"Создание slug для товара: '{name}'")
        
        try:
            slug = generate_unique_slug(name)
            logger.info(f"Slug сгенерирован: '{slug}'")
        except Exception as e:
            logger.error(f"Ошибка при генерации slug: {str(e)}")
            return jsonify({'error': 'Ошибка при генерации URL товара'}), 500

        product = Product(
            name=name,
            article=data.get('article', ''),
            slug=slug,
            price=data.get('price', 0),
            wholesale_price=data.get('wholesale_price', 0),
            quantity=data.get('quantity', 0),
            status=status,
            is_visible=data.get('is_visible', True),
            country=data.get('country', ''),
            brand=brand,
            description=data.get('description', ''),
            category_id=data.get('category_id'),
            is_draft=False
        )
        
        logger.info(f"Товар создан в памяти: name='{product.name}', article='{product.article}'")
        
        db.session.add(product)
        db.session.commit()
        
        logger.info(f"Товар успешно сохранен в БД: ID={product.id}")
        return jsonify({'message': 'Product created', 'id': product.id}), 201
        
    except Exception as e:
        logger.error(f"=== ОШИБКА ПРИ СОЗДАНИИ ТОВАРА ===")
        logger.error(f"Тип ошибки: {type(e).__name__}")
        logger.error(f"Сообщение ошибки: {str(e)}")
        logger.error(f"Детали ошибки: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'error': 'Ошибка при создании товара', 'details': str(e)}), 500


# 🔹 Обновить товар
@products_bp.route('/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    try:
        logger.info(f"Начало обновления товара ID: {product_id}")
        product = Product.query.get_or_404(product_id)
        data = request.json or {}
        logger.info(f"Получены данные для обновления: {list(data.keys())}")

        # Простая обработка статуса и бренда
        status = data.get('status', product.status)
        brand = data.get('brand', product.brand)
        
        # Обработка 'no'
        if str(status) == 'no':
            status = None
        if str(brand) == 'no':
            brand = ''

        new_name = data.get('name', product.name)
        if new_name != product.name:
            logger.info(f"Изменение названия товара: '{product.name}' -> '{new_name}'")
            try:
                product.slug = generate_unique_slug(new_name, product.id)
                logger.info(f"Новый slug сгенерирован: '{product.slug}'")
            except Exception as e:
                logger.error(f"Ошибка при генерации slug: {str(e)}")
                return jsonify({'error': 'Ошибка при генерации URL товара'}), 500

        product.name = new_name
        product.article = data.get('article', product.article)
        product.price = data.get('price', product.price)
        product.wholesale_price = data.get('wholesale_price', product.wholesale_price)
        product.quantity = data.get('quantity', product.quantity)
        product.status = status
        product.brand = brand
        product.is_visible = data.get('is_visible', product.is_visible)
        product.country = data.get('country', product.country)
        product.description = data.get('description', product.description)
        product.category_id = data.get('category_id', product.category_id)

        logger.info(f"Поля товара обновлены: name='{product.name}', article='{product.article}'")
        
        db.session.commit()
        logger.info(f"Товар успешно обновлен: ID={product.id}")
        return jsonify({'message': 'Product updated'})
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении товара ID {product_id}: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Ошибка при обновлении товара'}), 500


# 🔹 Удалить товар + папку
@products_bp.route('/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    ProductMedia.query.filter_by(product_id=product_id).delete()
    ProductDocument.query.filter_by(product_id=product_id).delete()

    folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', str(product_id))
    try:
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            print(f"Папка {folder_path} удалена при удалении товара.")
    except Exception as e:
        print(f"Ошибка при удалении папки: {e}")

    db.session.delete(product)
    db.session.commit()
    return jsonify({'message': 'Product deleted'})

@products_bp.route('/search', methods=['GET'])
def search_products():
    """Поиск товаров по названию"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify([])
    
    # Поиск товаров, название которых содержит введенный текст (регистронезависимо)
    products = Product.query.filter(
        Product.name.ilike(f'%{query}%'),
        Product.is_visible == True,
        Product.is_draft == False
    ).limit(10).all()
    
    result = []
    for p in products:
        first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
            .order_by(ProductMedia.order).first()
        
        result.append({
            'id': p.id,
            'name': p.name,
            'slug': p.slug,
            'article': p.article,
            'price': p.price,
            'wholesale_price': p.wholesale_price,
            'quantity': p.quantity,
            'status': 'no' if p.status is None else str(p.status),
            'is_visible': p.is_visible,
            'country': p.country,
            'brand': 'no' if not p.brand else p.brand,
            'description': p.description,
            'category_id': p.category_id,
            'image': first_image.url if first_image else None
        })
    
    return jsonify(result)

@products_bp.route('/brand/<string:brand_name>', methods=['GET'])
def get_products_by_brand(brand_name):
    """Получить товары по бренду"""
    try:
        # Декодируем название бренда из URL
        import urllib.parse
        brand_name = urllib.parse.unquote(brand_name)
        
        # Получаем товары по бренду
        products = Product.query.filter(
            Product.brand == brand_name,
            Product.is_visible == True,
            Product.is_draft == False
        ).all()
        
        result = []
        for p in products:
            first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
                .order_by(ProductMedia.order).first()
            
            result.append({
                'id': p.id,
                'name': p.name,
                'slug': p.slug,
                'article': p.article,
                'price': p.price,
                'wholesale_price': p.wholesale_price,
                'quantity': p.quantity,
                'status': 'no' if p.status is None else str(p.status),
                'is_visible': p.is_visible,
                'country': p.country,
                'brand': 'no' if not p.brand else p.brand,
                'description': p.description,
                'category_id': p.category_id,
                'image': first_image.url if first_image else None
            })
        
        return jsonify({
            'brand': brand_name,
            'products': result,
            'total_count': len(result)
        })
    except Exception as e:
        logger.error(f"Error getting products by brand {brand_name}: {str(e)}")
        return jsonify({'error': 'Ошибка получения товаров по бренду'}), 500

@products_bp.route('/brand/<string:brand_name>/categories', methods=['GET'])
def get_categories_by_brand(brand_name):
    """Получить категории товаров по бренду для фильтрации"""
    try:
        # Декодируем название бренда из URL
        import urllib.parse
        brand_name = urllib.parse.unquote(brand_name)
        
        # Получаем уникальные категории товаров по бренду
        from models.category import Category
        
        # Подзапрос для получения ID категорий товаров данного бренда
        category_ids = db.session.query(Product.category_id).filter(
            Product.brand == brand_name,
            Product.is_visible == True,
            Product.is_draft == False,
            Product.category_id.isnot(None)
        ).distinct().all()
        
        category_ids = [cat_id[0] for cat_id in category_ids]
        
        if not category_ids:
            return jsonify({'categories': []})
        
        # Получаем категории
        categories = Category.query.filter(Category.id.in_(category_ids)).all()
        
        result = []
        for cat in categories:
            # Подсчитываем количество товаров в каждой категории для данного бренда
            product_count = Product.query.filter(
                Product.brand == brand_name,
                Product.category_id == cat.id,
                Product.is_visible == True,
                Product.is_draft == False
            ).count()
            
            result.append({
                'id': cat.id,
                'name': cat.name,
                'slug': cat.slug,
                'parent_id': cat.parent_id,
                'description': cat.description,
                'image_url': cat.image_url,
                'order': cat.order,
                'product_count': product_count
            })
        
        # Сортируем по количеству товаров (по убыванию)
        result.sort(key=lambda x: x['product_count'], reverse=True)
        
        return jsonify({
            'brand': brand_name,
            'categories': result
        })
    except Exception as e:
        logger.error(f"Error getting categories by brand {brand_name}: {str(e)}")
        return jsonify({'error': 'Ошибка получения категорий по бренду'}), 500

@products_bp.route('/brand/<string:brand_name>/filter', methods=['GET'])
def get_products_by_brand_and_category(brand_name):
    """Получить товары по бренду с фильтрацией по категории"""
    try:
        # Декодируем название бренда из URL
        import urllib.parse
        brand_name = urllib.parse.unquote(brand_name)
        
        # Получаем параметры фильтрации
        category_id = request.args.get('category_id', type=int)
        
        # Базовый запрос
        query = Product.query.filter(
            Product.brand == brand_name,
            Product.is_visible == True,
            Product.is_draft == False
        )
        
        # Добавляем фильтр по категории, если указан
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        products = query.all()
        
        result = []
        for p in products:
            first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
                .order_by(ProductMedia.order).first()
            
            result.append({
                'id': p.id,
                'name': p.name,
                'slug': p.slug,
                'article': p.article,
                'price': p.price,
                'wholesale_price': p.wholesale_price,
                'quantity': p.quantity,
                'status': 'no' if p.status is None else str(p.status),
                'is_visible': p.is_visible,
                'country': p.country,
                'brand': 'no' if not p.brand else p.brand,
                'description': p.description,
                'category_id': p.category_id,
                'image': first_image.url if first_image else None
            })
        
        return jsonify({
            'brand': brand_name,
            'category_id': category_id,
            'products': result,
            'total_count': len(result)
        })
    except Exception as e:
        logger.error(f"Error filtering products by brand {brand_name}: {str(e)}")
        return jsonify({'error': 'Ошибка фильтрации товаров'}), 500
