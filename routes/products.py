import os
import shutil
import re
import unicodedata
import math
from flask import Blueprint, request, jsonify, current_app
import logging
from extensions import db
from models import ProductDocument, ProductCharacteristic
from models.product import Product
from models.media import ProductMedia
from models.brand import Brand
from models.supplier import Supplier
from models.product_availability_status import ProductAvailabilityStatus

products_bp = Blueprint('products', __name__)
logger = logging.getLogger(__name__)


def get_availability_status_for_quantity(quantity: int, statuses_cache=None):
    """Возвращает статус наличия на основе таблицы product_availability_statuses."""
    statuses = statuses_cache
    if statuses is None:
        statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()

    for status in statuses:
        if status.check_condition(quantity):
            return status.to_dict()

    return None

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
            brand_id=None,
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
@products_bp.route('/<int:product_id>/finalize', methods=['PUT'])
def finalize_product(product_id):
    try:
        logger.info(f"Начало финализации товара ID: {product_id}")
        
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
            
            # Обработка статуса
            status = data.get('status', product.status)
            if str(status) == 'no':
                status = None
            
            # Обработка бренда: используем только brand_id
            brand_id = data.get('brand_id', product.brand_id)
            
            if brand_id is not None and brand_id:
                # Проверяем существование бренда
                brand_obj = Brand.query.get(brand_id)
                if not brand_obj:
                    return jsonify({'error': f'Бренд с ID {brand_id} не найден'}), 400
            elif brand_id == '' or brand_id == 'no':
                brand_id = None

            product.status = status            
            product.is_visible = data.get('is_visible', False)
            product.country = data.get('country', '')
            product.brand_id = brand_id
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


def serialize_product(product, availability_status=None):
    first_image = ProductMedia.query.filter_by(product_id=product.id, media_type='image') \
        .order_by(ProductMedia.order).first()

    brand_info = None
    if product.brand_id and product.brand_info:
        brand_info = {
            'id': product.brand_info.id,
            'name': product.brand_info.name,
            'country': product.brand_info.country,
            'description': product.brand_info.description,
            'image_url': product.brand_info.image_url
        }

    supplier_info = None
    if getattr(product, 'supplier', None):
        supplier_info = {
            'id': product.supplier.id,
            'name': product.supplier.name
        }

    status_value = 'no' if product.status is None else str(product.status)

    if availability_status is None:
        availability_status = get_availability_status_for_quantity(product.quantity or 0)

    product_data = {
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'article': product.article,
        'price': product.price,
        'wholesale_price': product.wholesale_price,
        'quantity': product.quantity,
        'status': status_value,
        'is_visible': product.is_visible,
        'is_draft': product.is_draft,
        'country': product.country,
        'brand_id': product.brand_id,
        'brand_info': brand_info,
        'supplier_id': getattr(product, 'supplier_id', None),
        'supplier': supplier_info,
        'description': product.description,
        'category_id': product.category_id,
        'category': product.category.name if product.category else None,
        'image': first_image.url if first_image else None,
        'availability_status': availability_status
    }

    return product_data


@products_bp.route('/bulk', methods=['GET'])
def get_products_bulk():
    ids_param = request.args.get('ids', '')
    if not ids_param:
        return jsonify([])

    try:
        id_list = [int(id_str) for id_str in ids_param.split(',') if id_str.strip()]
    except ValueError:
        return jsonify({'error': 'Некорректный список идентификаторов'}), 400

    if not id_list:
        return jsonify([])

    products = Product.query.filter(Product.id.in_(id_list)).all()
    availability_statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()
    index_map = {product_id: index for index, product_id in enumerate(id_list)}

    serialized_items = []
    for product in products:
        availability_status = get_availability_status_for_quantity(product.quantity or 0, availability_statuses)
        serialized_items.append((
            index_map.get(product.id, len(id_list)),
            serialize_product(product, availability_status)
        ))

    serialized_items.sort(key=lambda item: item[0])
    return jsonify([item[1] for item in serialized_items])


@products_bp.route('/', methods=['GET'])
def get_products():
    try:
        page = request.args.get('page', type=int)
        per_page = request.args.get('per_page', type=int)
        search = request.args.get('search', type=str, default='').strip()
        category_param = request.args.get('category_id')
        status_param = request.args.get('status')
        brand_param = request.args.get('brand')
        supplier_param = request.args.get('supplier')
        visibility_param = request.args.get('visibility')
        quantity_param = request.args.get('quantity')

        query = Product.query

        if search:
            query = query.filter(Product.name.ilike(f'%{search}%'))

        if category_param:
            if category_param == 'no-category':
                query = query.filter(Product.category_id.is_(None))
            else:
                try:
                    category_id_int = int(category_param)
                    query = query.filter(Product.category_id == category_id_int)
                except (TypeError, ValueError):
                    pass

        if status_param:
            if status_param == 'no-status':
                query = query.filter(Product.status.is_(None))
            else:
                try:
                    status_id = int(status_param)
                    query = query.filter(Product.status == status_id)
                except (TypeError, ValueError):
                    pass

        if brand_param:
            if brand_param in ('no', 'no-brand'):
                query = query.filter(Product.brand_id.is_(None))
            else:
                brand_id = None
                try:
                    brand_id = int(brand_param)
                except (TypeError, ValueError):
                    brand_obj = Brand.query.filter_by(name=brand_param).first()
                    if brand_obj:
                        brand_id = brand_obj.id
                if brand_id:
                    query = query.filter(Product.brand_id == brand_id)

        supplier_column = getattr(Product, 'supplier_id', None)
        if supplier_param and supplier_column is not None:
            if supplier_param == 'no-supplier':
                query = query.filter(Product.supplier_id.is_(None))
            else:
                try:
                    supplier_id = int(supplier_param)
                    query = query.filter(Product.supplier_id == supplier_id)
                except (TypeError, ValueError):
                    pass

        if visibility_param == 'true':
            query = query.filter(Product.is_visible.is_(True))
        elif visibility_param == 'false':
            query = query.filter(Product.is_visible.is_(False))

        if quantity_param == 'true':
            query = query.filter(Product.quantity > 0)
        elif quantity_param == 'false':
            query = query.filter(Product.quantity <= 0)

        query = query.order_by(Product.id.desc())

        if per_page:
            per_page = max(1, min(per_page, 200))
            current_page = max(1, page or 1)
            total_count = query.count()
            total_pages = math.ceil(total_count / per_page) if total_count else 1
            if current_page > total_pages and total_pages > 0:
                current_page = total_pages
            pagination = query.paginate(page=current_page, per_page=per_page, error_out=False)
            products = pagination.items
            total_count = pagination.total
            total_pages = pagination.pages if pagination.pages else 1
            availability_statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()
            result = [
                serialize_product(
                    product,
                    availability_status=get_availability_status_for_quantity(product.quantity or 0, availability_statuses)
                ) for product in products
            ]
            return jsonify({
                'products': result,
                'page': current_page,
                'per_page': per_page,
                'total_pages': total_pages,
                'total_count': total_count
            })

        products = query.all()
        result = [serialize_product(product) for product in products]
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting products list: {str(e)}")
        return jsonify({'error': 'Ошибка получения товаров'}), 500


# 🔹 Получить товар по slug
@products_bp.route('/<string:slug>', methods=['GET'])
def get_product_by_slug(slug):
    product = Product.query.filter_by(slug=slug).first_or_404()

    first_image = ProductMedia.query.filter_by(product_id=product.id, media_type='image') \
        .order_by(ProductMedia.order).first()

    # 🧩 Все характеристики
    characteristics = ProductCharacteristic.query.filter_by(product_id=product.id).all()
    characteristics_data = []
    for c in characteristics:
        # Получаем данные из справочника характеристик по ID из поля key
        try:
            characteristic_id = int(c.key) if c.key else None
        except (ValueError, TypeError):
            characteristic_id = None
            
        if characteristic_id:
            from models.characteristics_list import CharacteristicsList
            characteristic_info = CharacteristicsList.query.get(characteristic_id)
            if characteristic_info:
                characteristics_data.append({
                    'id': c.id,
                    'key': characteristic_info.characteristic_key,
                    'value': c.value,
                    'sort_order': c.sort_order,
                    'unit_of_measurement': characteristic_info.unit_of_measurement or ''
                })

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

    # Получаем информацию о бренде
    brand_info = None
    if product.brand_id and product.brand_info:
        brand_info = {
            'id': product.brand_info.id,
            'name': product.brand_info.name,
            'country': product.brand_info.country,
            'description': product.brand_info.description,
            'image_url': product.brand_info.image_url
        }

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
        'brand_id': product.brand_id,
        'brand_info': brand_info,  # Полная информация о бренде
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
        logger.info("Начало создания товара")
        data = request.json or {}
        logger.info(f"Получены данные: {list(data.keys())}")

        # Обработка статуса
        status = data.get('status')
        if str(status) == 'no':
            status = None
        
        # Обработка бренда: используем только brand_id
        brand_id = data.get('brand_id')
        
        # Если передан brand_id, проверяем существование бренда
        if brand_id:
            brand_obj = Brand.query.get(brand_id)
            if not brand_obj:
                return jsonify({'error': f'Бренд с ID {brand_id} не найден'}), 400

        supplier_id = data.get('supplier_id')
        if supplier_id in (None, '', 'no-supplier'):
            supplier_id = None
        elif supplier_id is not None:
            try:
                supplier_id = int(supplier_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Некорректный идентификатор поставщика'}), 400
            if supplier_id:
                supplier_obj = Supplier.query.get(supplier_id)
                if not supplier_obj:
                    return jsonify({'error': f'Поставщик с ID {supplier_id} не найден'}), 400

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
            brand_id=brand_id,
            supplier_id=supplier_id,
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
        logger.error(f"Ошибка при создании товара: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Ошибка при создании товара'}), 500


# 🔹 Обновить товар
@products_bp.route('/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    try:
        logger.info(f"Начало обновления товара ID: {product_id}")
        product = Product.query.get_or_404(product_id)
        data = request.json or {}
        logger.info(f"Получены данные для обновления: {list(data.keys())}")

        # Обработка статуса
        status = data.get('status', product.status)
        if str(status) == 'no':
            status = None
        
        # Обработка бренда: используем только brand_id
        brand_id = data.get('brand_id', product.brand_id)
        
        if brand_id is not None and brand_id:
            # Проверяем существование бренда
            brand_obj = Brand.query.get(brand_id)
            if not brand_obj:
                return jsonify({'error': f'Бренд с ID {brand_id} не найден'}), 400
        elif brand_id == '' or brand_id == 'no':
            brand_id = None

        supplier_id = data.get('supplier_id', getattr(product, 'supplier_id', None))
        if supplier_id in ('', 'no-supplier'):
            supplier_id = None
        elif supplier_id is not None:
            try:
                supplier_id = int(supplier_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Некорректный идентификатор поставщика'}), 400
            if supplier_id:
                supplier_obj = Supplier.query.get(supplier_id)
                if not supplier_obj:
                    return jsonify({'error': f'Поставщик с ID {supplier_id} не найден'}), 400

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
        product.brand_id = brand_id
        if hasattr(product, 'supplier_id'):
            product.supplier_id = supplier_id
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
        
        # Получаем информацию о бренде
        brand_info = None
        if p.brand_id and p.brand_info:
            brand_info = {
                'id': p.brand_info.id,
                'name': p.brand_info.name,
                'country': p.brand_info.country
            }
        
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
            'brand_id': p.brand_id,
            'brand_info': brand_info,
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
        
        # Пытаемся найти бренд по названию или ID
        brand_obj = None
        try:
            # Если это число, пытаемся найти по ID
            brand_id = int(brand_name)
            brand_obj = Brand.query.get(brand_id)
        except ValueError:
            # Если не число, ищем по названию
            brand_obj = Brand.query.filter_by(name=brand_name).first()
        
        if not brand_obj:
            return jsonify({
                'brand': None,
                'products': [],
                'total_count': 0,
                'error': 'Бренд не найден'
            }), 404
        
        # Получаем товары по brand_id
        products = Product.query.filter(
            Product.brand_id == brand_obj.id,
            Product.is_visible == True,
            Product.is_draft == False
        ).all()
        
        result = []
        for p in products:
            first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
                .order_by(ProductMedia.order).first()
            
            # Получаем информацию о бренде
            brand_info = None
            if p.brand_id and p.brand_info:
                brand_info = {
                    'id': p.brand_info.id,
                    'name': p.brand_info.name,
                    'country': p.brand_info.country,
                    'description': p.brand_info.description,
                    'image_url': p.brand_info.image_url
                }
            
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
                'brand_id': p.brand_id,
                'brand_info': brand_info,  # Добавляем brand_info
                'brand': brand_info,
                'description': p.description,
                'category_id': p.category_id,
                'image': first_image.url if first_image else None
            })
        
        return jsonify({
            'brand': {
                'id': brand_obj.id,
                'name': brand_obj.name,
                'country': brand_obj.country
            },
            'products': result,
            'total_count': len(result)
        })
    except Exception as e:
        logger.error(f"Error getting products by brand {brand_name}: {str(e)}")
        return jsonify({'error': 'Ошибка получения товаров по бренду'}), 500

@products_bp.route('/brand/<string:brand_name>/detailed', methods=['GET'])
def get_products_by_brand_detailed(brand_name):
    """Получить товары по бренду с полной информацией (статус, бренд, категория)"""
    try:
        # Декодируем название бренда из URL
        import urllib.parse
        brand_name = urllib.parse.unquote(brand_name)
        
        # Импортируем необходимые модели
        from models.status import Status
        from models.brand import Brand
        from models.category import Category
        
        # Пытаемся найти бренд по названию или ID
        brand_obj = None
        try:
            # Если это число, пытаемся найти по ID
            brand_id = int(brand_name)
            brand_obj = Brand.query.get(brand_id)
        except ValueError:
            # Если не число, ищем по названию
            brand_obj = Brand.query.filter_by(name=brand_name).first()
        
        if not brand_obj:
            return jsonify({
                'brand': None,
                'products': [],
                'total_count': 0,
                'error': 'Бренд не найден'
            }), 404
        
        # Параметры пагинации
        page = request.args.get('page', default=1, type=int) or 1
        per_page = request.args.get('per_page', default=20, type=int) or 20
        per_page = max(1, min(per_page, 100))

        query = Product.query.filter(
            Product.brand_id == brand_obj.id,
            Product.is_visible == True,
            Product.is_draft == False
        ).order_by(Product.id.desc())

        total_count = query.count()
        total_pages = math.ceil(total_count / per_page) if total_count else 0

        if total_pages and page > total_pages:
            page = total_pages
        if page < 1:
            page = 1

        products = query.offset((page - 1) * per_page).limit(per_page).all()
        availability_statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()

        result = []
        for p in products:
            # Получаем первое изображение
            first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
                .order_by(ProductMedia.order).first()
            
            # Получаем информацию о статусе
            status_info = None
            if p.status:
                status_obj = Status.query.get(p.status)
                if status_obj:
                    status_info = {
                        'id': status_obj.id,
                        'name': status_obj.name,
                        'background_color': status_obj.background_color,
                        'text_color': status_obj.text_color
                    }
            
            # Получаем информацию о бренде из relationship
            brand_info = None
            if p.brand_id and p.brand_info:
                brand_info = {
                    'id': p.brand_info.id,
                    'name': p.brand_info.name,
                    'country': p.brand_info.country,
                    'description': p.brand_info.description,
                    'image_url': p.brand_info.image_url
                }
            
            # Получаем информацию о категории
            category_info = None
            if p.category_id:
                category_obj = Category.query.get(p.category_id)
                if category_obj:
                    category_info = {
                        'id': category_obj.id,
                        'name': category_obj.name,
                        'slug': category_obj.slug,
                        'description': category_obj.description,
                        'image_url': category_obj.image_url
                    }
            
            # Получаем статус наличия на основе таблицы
            availability_status = get_availability_status_for_quantity(p.quantity or 0, availability_statuses)
            
            result.append({
                'id': p.id,
                'name': p.name,
                'slug': p.slug,
                'article': p.article,
                'price': p.price,
                'wholesale_price': p.wholesale_price,
                'quantity': p.quantity,
                'is_visible': p.is_visible,
                'description': p.description,
                'category_id': p.category_id,
                'image_url': first_image.url if first_image else None,
                'status': status_info,
                'brand_id': p.brand_id,
                'brand_info': brand_info,  # Используем brand_info вместо brand
                'brand': brand_info,  # Для обратной совместимости
                'category': category_info,
                'availability_status': availability_status
            })
        
        return jsonify({
            'brand': {
                'id': brand_obj.id,
                'name': brand_obj.name,
                'country': brand_obj.country,
                'description': brand_obj.description,
                'image_url': brand_obj.image_url
            },
            'products': result,
            'total_count': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages
        })
    except Exception as e:
        logger.error(f"Error getting detailed products by brand {brand_name}: {str(e)}")
        return jsonify({'error': 'Ошибка получения детальной информации о товарах по бренду'}), 500

@products_bp.route('/brand/<string:brand_name>/categories', methods=['GET'])
def get_categories_by_brand(brand_name):
    """Получить категории товаров по бренду для фильтрации"""
    try:
        # Декодируем название бренда из URL
        import urllib.parse
        brand_name = urllib.parse.unquote(brand_name)
        
        # Получаем уникальные категории товаров по бренду
        from models.category import Category
        
        # Пытаемся найти бренд по названию или ID
        brand_obj = None
        try:
            brand_id = int(brand_name)
            brand_obj = Brand.query.get(brand_id)
        except ValueError:
            brand_obj = Brand.query.filter_by(name=brand_name).first()
        
        if not brand_obj:
            return jsonify({'categories': []})
        
        # Подзапрос для получения ID категорий товаров данного бренда
        category_ids = db.session.query(Product.category_id).filter(
            Product.brand_id == brand_obj.id,
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
                Product.brand_id == brand_obj.id,
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
            'brand': {
                'id': brand_obj.id,
                'name': brand_obj.name,
                'country': brand_obj.country
            },
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
        
        # Пытаемся найти бренд по названию или ID
        brand_obj = None
        try:
            brand_id = int(brand_name)
            brand_obj = Brand.query.get(brand_id)
        except ValueError:
            brand_obj = Brand.query.filter_by(name=brand_name).first()
        
        if not brand_obj:
            return jsonify({
                'brand': None,
                'products': [],
                'total_count': 0,
                'error': 'Бренд не найден'
            }), 404
        
        # Получаем параметры фильтрации
        category_param = request.args.get('category_id')
        category_id_value = None
        page = request.args.get('page', default=1, type=int) or 1
        per_page = request.args.get('per_page', default=20, type=int) or 20
        per_page = max(1, min(per_page, 100))
        
        # Базовый запрос
        query = Product.query.filter(
            Product.brand_id == brand_obj.id,
            Product.is_visible == True,
            Product.is_draft == False
        )
        
        # Добавляем фильтр по категории, если указан
        if category_param:
            if category_param == 'no-category':
                query = query.filter(Product.category_id.is_(None))
                category_id_value = None
            else:
                try:
                    category_id_int = int(category_param)
                    query = query.filter(Product.category_id == category_id_int)
                    category_id_value = category_id_int
                except (TypeError, ValueError):
                    pass
        
        query = query.order_by(Product.id.desc())

        total_count = query.count()
        total_pages = math.ceil(total_count / per_page) if total_count else 0

        if total_pages and page > total_pages:
            page = total_pages
        if page < 1:
            page = 1

        products = query.offset((page - 1) * per_page).limit(per_page).all()
        availability_statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()

        result = []
        from models.status import Status

        for p in products:
            first_image = ProductMedia.query.filter_by(product_id=p.id, media_type='image') \
                .order_by(ProductMedia.order).first()
            
            # Получаем информацию о бренде
            brand_info = None
            if p.brand_id and p.brand_info:
                brand_info = {
                    'id': p.brand_info.id,
                    'name': p.brand_info.name,
                    'country': p.brand_info.country,
                    'description': p.brand_info.description,
                    'image_url': p.brand_info.image_url
                }
            
            status_info = None
            if p.status:
                status_obj = Status.query.get(p.status)
                if status_obj:
                    status_info = {
                        'id': status_obj.id,
                        'name': status_obj.name,
                        'background_color': status_obj.background_color,
                        'text_color': status_obj.text_color
                    }
            availability_status = get_availability_status_for_quantity(p.quantity or 0, availability_statuses)
            
            result.append({
                'id': p.id,
                'name': p.name,
                'slug': p.slug,
                'article': p.article,
                'price': p.price,
                'wholesale_price': p.wholesale_price,
                'quantity': p.quantity,
                'status': status_info,
                'is_visible': p.is_visible,
                'country': p.country,
                'brand_id': p.brand_id,
                'brand_info': brand_info,  # Добавляем brand_info
                'description': p.description,
                'category_id': p.category_id,
                'image': first_image.url if first_image else None,
                'availability_status': availability_status
            })
        
        return jsonify({
            'brand': {
                'id': brand_obj.id,
                'name': brand_obj.name,
                'country': brand_obj.country
            },
            'category_id': category_id_value,
            'products': result,
            'total_count': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages
        })
    except Exception as e:
        logger.error(f"Error filtering products by brand {brand_name}: {str(e)}")
        return jsonify({'error': 'Ошибка фильтрации товаров'}), 500
