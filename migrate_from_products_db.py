"""
Скрипт для миграции данных из старой базы products.db в новую базу через API.

Порядок выполнения:
1. Создание брендов (наименование и страна)
2. Создание категорий (наименование)
3. Создание товаров с привязкой к категориям и брендам, установка цены
4. Добавление ссылок на изображения в медиа
"""

import sqlite3
import requests
import time
import os
import sys
from urllib.parse import quote
import unicodedata
import re

# Настройки API
# По умолчанию используем Render сервер, можно переопределить через переменную окружения или аргумент
API_BASE_URL = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
OLD_DB_PATH = os.path.join(os.path.dirname(__file__), 'products.db')

# Словари для маппинга старых ID на новые
brands_map = {}  # {old_brand_name: new_brand_id}
categories_map = {}  # {old_category_id: new_category_id}
brands_cache = {}  # {(name, country): brand_id} для быстрого поиска
categories_cache = {}  # {(name, parent_id): category_id} для быстрого поиска
products_cache = {}  # {article: product_id} для быстрого поиска товаров по артикулу
products_by_name_brand = {}  # {(name, brand): product_id} для поиска по имени+бренду
existing_brands_loaded = False  # Флаг загрузки существующих брендов
existing_categories_loaded = False  # Флаг загрузки существующих категорий
existing_products_loaded = False  # Флаг загрузки существующих товаров


def normalize_url(api_url, endpoint):
    """
    Нормализует URL, убирая /api из пути для эндпоинтов, которые не имеют префикса /api
    """
    # Убираем /api из базового URL, если он есть
    base_url = api_url.replace('/api', '') if '/api' in api_url else api_url
    # Убираем лишние слеши
    base_url = base_url.rstrip('/')
    endpoint = endpoint.lstrip('/')
    return f"{base_url}/{endpoint}"


def safe_slugify(text):
    """Создание slug из текста"""
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
    
    for russian, latin in russian_to_latin.items():
        text = text.replace(russian, latin)
    
    # Удаляем все символы кроме букв, цифр и пробелов
    text = re.sub(r'[^\w\s-]', '', text)
    
    # Заменяем пробелы на дефисы
    text = re.sub(r'[-\s]+', '-', text)
    
    # Удаляем начальные и конечные дефисы
    text = text.strip('-')
    
    return text.lower()


def check_db_structure(conn):
    """Проверяет структуру базы данных и возвращает список таблиц и их колонок"""
    cursor = conn.cursor()
    
    # Получаем список таблиц
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"Найдено таблиц: {len(tables)}")
    print(f"Таблицы: {', '.join(tables)}")
    
    structure = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]
        structure[table] = columns
        print(f"\nТаблица '{table}' колонки: {', '.join(columns)}")
    
    return structure


def load_existing_brands(api_url):
    """Загружает все существующие бренды в кеш"""
    global existing_brands_loaded, brands_cache
    
    if existing_brands_loaded:
        return
    
    brands_url = normalize_url(api_url, 'meta/brands')
    print(f"  Загрузка существующих брендов с {brands_url}...")
    try:
        # Увеличиваем таймаут для Render (может "просыпаться" до 30 секунд)
        response = requests.get(brands_url, timeout=60)
        if response.status_code == 200:
            existing_brands = response.json()
            for brand in existing_brands:
                cache_key = (brand.get('name', ''), brand.get('country', ''))
                brands_cache[cache_key] = brand['id']
            existing_brands_loaded = True
            print(f"  ✓ Загружено {len(brands_cache)} существующих брендов в кеш")
        else:
            print(f"  ⚠ Ошибка загрузки брендов: {response.status_code}")
    except requests.exceptions.Timeout:
        print(f"  ⚠ Таймаут при загрузке брендов (сервер может быть в режиме сна)")
        print(f"     Попробуйте подождать несколько секунд и запустить снова")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке существующих брендов: {e}")


def create_brand(name, country='', api_url=None):
    """Создает бренд через API с проверкой на дубликаты"""
    # Используем переданный API URL или глобальный
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    # Загружаем существующие бренды при первом вызове
    load_existing_brands(api_url)
    
    # Проверяем кеш
    cache_key = (name, country)
    if cache_key in brands_cache:
        existing_id = brands_cache[cache_key]
        print(f"  ✓ Бренд '{name}' ({country}) уже существует (ID: {existing_id}), пропускаем")
        return existing_id
    
    # Создаем новый бренд
    brands_url = normalize_url(api_url, 'meta/brands')
    try:
        data = {
            'name': name,
            'country': country or '',
            'description': '',
            'image_url': None
        }
        response = requests.post(
            brands_url,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=60  # Увеличенный таймаут для Render
        )
        
        if response.status_code == 200:
            result = response.json()
            brand_id = result.get('id')
            brands_cache[cache_key] = brand_id  # Сохраняем в кеш
            print(f"✓ Создан бренд: {name} (ID: {brand_id})")
            return brand_id
        else:
            print(f"✗ Ошибка создания бренда {name}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"✗ Ошибка при создании бренда {name}: {e}")
        return None


def load_existing_categories(api_url):
    """Загружает все существующие категории в кеш"""
    global existing_categories_loaded, categories_cache
    
    if existing_categories_loaded:
        return
    
    categories_url = normalize_url(api_url, 'categories/')
    print(f"  Загрузка существующих категорий с {categories_url}...")
    try:
        # Увеличиваем таймаут для Render (может "просыпаться" до 30 секунд)
        response = requests.get(categories_url, timeout=60)
        if response.status_code == 200:
            existing_categories = response.json()
            for category in existing_categories:
                cache_key = (category.get('name', ''), category.get('parent_id'))
                categories_cache[cache_key] = category['id']
            existing_categories_loaded = True
            print(f"  ✓ Загружено {len(categories_cache)} существующих категорий в кеш")
        else:
            print(f"  ⚠ Ошибка загрузки категорий: {response.status_code}")
    except requests.exceptions.Timeout:
        print(f"  ⚠ Таймаут при загрузке категорий (сервер может быть в режиме сна)")
        print(f"     Попробуйте подождать несколько секунд и запустить снова")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке существующих категорий: {e}")


def create_category(name, parent_id=None, api_url=None):
    """Создает категорию через API с проверкой на дубликаты"""
    if not name:
        return None
    
    # Используем переданный API URL или глобальный
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    # Загружаем существующие категории при первом вызове
    load_existing_categories(api_url)
    
    # Проверяем кеш
    cache_key = (name, parent_id)
    if cache_key in categories_cache:
        existing_id = categories_cache[cache_key]
        print(f"  ✓ Категория '{name}' уже существует (ID: {existing_id}), пропускаем")
        return existing_id
    
    # Генерируем slug
    slug = safe_slugify(name)
    if not slug:
        slug = f"category-{int(time.time())}"
    
    try:
        # Используем multipart/form-data для создания категории (без файла)
        data = {
            'name': name,
            'slug': slug,
            'description': '',
            'parent_id': parent_id if parent_id else ''
        }
        categories_url = normalize_url(api_url, 'categories/with-image')
        response = requests.post(
            categories_url,
            data=data,
            timeout=60  # Увеличенный таймаут для Render
        )
        
        if response.status_code == 201:
            result = response.json()
            category_id = result.get('id')
            categories_cache[cache_key] = category_id
            print(f"✓ Создана категория: {name} (ID: {category_id})")
            return category_id
        else:
            print(f"✗ Ошибка создания категории {name}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"✗ Ошибка при создании категории {name}: {e}")
        return None


def load_existing_products(api_url):
    """Загружает все существующие товары в кеш (по артикулу и по имени+бренду)"""
    global existing_products_loaded, products_cache, products_by_name_brand
    
    if existing_products_loaded:
        return
    
    products_url = normalize_url(api_url, 'products/')
    print(f"  Загрузка существующих товаров с {products_url}...")
    try:
        # Увеличиваем таймаут для Render (может "просыпаться" до 30 секунд)
        response = requests.get(products_url, timeout=60)
        if response.status_code == 200:
            existing_products = response.json()
            for product in existing_products:
                article = product.get('article', '')
                name = product.get('name', '')
                brand = product.get('brand', '') or ''
                
                # Кешируем по артикулу (если есть)
                if article:
                    products_cache[article] = product['id']
                
                # Кешируем по имени+бренду (для проверки дубликатов без артикула)
                if name:
                    cache_key = (name.strip(), brand.strip())
                    products_by_name_brand[cache_key] = product['id']
            
            existing_products_loaded = True
            print(f"  ✓ Загружено {len(existing_products)} существующих товаров в кеш")
            print(f"    - По артикулу: {len(products_cache)}")
            print(f"    - По имени+бренду: {len(products_by_name_brand)}")
        else:
            print(f"  ⚠ Ошибка загрузки товаров: {response.status_code}")
    except requests.exceptions.Timeout:
        print(f"  ⚠ Таймаут при загрузке товаров (сервер может быть в режиме сна)")
        print(f"     Попробуйте подождать несколько секунд и запустить снова")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке существующих товаров: {e}")


def create_product(product_data, brand_id, category_id, price, api_url=None):
    """Создает товар через API с проверкой на дубликаты по артикулу и по имени+бренду"""
    # Используем переданный API URL или глобальный
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    # Загружаем существующие товары при первом вызове
    load_existing_products(api_url)
    
    # Получаем данные для проверки
    article = product_data.get('article', '') or product_data.get('code', '')
    name = product_data.get('name', '').strip()
    brand_name = product_data.get('brand_name', '') or product_data.get('brand', '') or ''
    brand_name = brand_name.strip()
    
    # Проверяем на дубликат по артикулу (если артикул есть)
    if article and article in products_cache:
        existing_id = products_cache[article]
        print(f"  ⚠ Товар с артикулом '{article}' уже существует (ID: {existing_id}), пропускаем")
        return existing_id
    
    # Проверяем на дубликат по имени+бренду (если артикула нет или для дополнительной проверки)
    if name:
        cache_key = (name, brand_name)
        if cache_key in products_by_name_brand:
            existing_id = products_by_name_brand[cache_key]
            print(f"  ⚠ Товар '{name}' (бренд: '{brand_name}') уже существует (ID: {existing_id}), пропускаем")
            return existing_id
    
    # Если артикула нет, генерируем уникальный на основе имени
    if not article or not article.strip():
        import hashlib
        # Генерируем артикул на основе имени и timestamp
        name_hash = hashlib.md5(name.encode('utf-8')).hexdigest()[:8].upper()
        timestamp = int(time.time() * 1000) % 1000000  # Увеличиваем диапазон для уникальности
        article = f"MIGR-{name_hash}-{timestamp}"
        print(f"  ℹ Генерирован артикул для товара без артикула: {article}")
    
    try:
        data = {
            'name': name,
            'article': article,
            'price': float(price) if price else 0,
            'wholesale_price': product_data.get('wholesale_price', 0),
            'quantity': product_data.get('quantity', 0),
            'status': None,
            'is_visible': True,
            'country': product_data.get('country', ''),
            'brand': brand_name,
            'description': product_data.get('description', ''),
            'category_id': category_id
        }
        products_url = normalize_url(api_url, 'products/')
        response = requests.post(
            products_url,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=60  # Увеличенный таймаут для Render
        )
        
        if response.status_code == 201:
            result = response.json()
            product_id = result.get('id')
            # Сохраняем в кеш
            products_cache[article] = product_id
            if name:
                cache_key = (name, brand_name)
                products_by_name_brand[cache_key] = product_id
            print(f"✓ Создан товар: {name} (ID: {product_id}, артикул: {article})")
            return product_id
        else:
            error_text = response.text
            # Проверяем, не является ли это ошибкой дубликата артикула
            if 'UniqueViolation' in error_text or 'product_article_key' in error_text or 'duplicate key' in error_text.lower():
                print(f"  ⚠ Товар с артикулом '{article}' уже существует (ошибка уникальности), пропускаем")
                # Пытаемся найти существующий товар по имени+бренду
                if name:
                    cache_key = (name, brand_name)
                    if cache_key in products_by_name_brand:
                        return products_by_name_brand[cache_key]
                return None
            print(f"✗ Ошибка создания товара {name}: {response.status_code} - {error_text[:200]}")
            return None
    except Exception as e:
        print(f"✗ Ошибка при создании товара {product_data.get('name', '')}: {e}")
        return None


def add_media(product_id, image_url, api_url=None):
    """Добавляет медиа (изображение) для товара"""
    if not image_url:
        return False
    
    # Используем переданный API URL или глобальный
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    try:
        data = {
            'url': image_url,
            'media_type': 'image'
        }
        upload_url = normalize_url(api_url, f'upload/media/{product_id}')
        response = requests.post(
            upload_url,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=60  # Увеличенный таймаут для Render
        )
        
        if response.status_code == 201:
            print(f"  ✓ Добавлено изображение: {image_url}")
            return True
        else:
            print(f"  ✗ Ошибка добавления изображения {image_url}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"  ✗ Ошибка при добавлении изображения {image_url}: {e}")
        return False


def migrate_data(api_base_url=None, db_path=None, skip_brands=False, skip_categories=False):
    """
    Основная функция миграции
    
    Args:
        api_base_url: URL API сервера
        db_path: Путь к файлу products.db
        skip_brands: Если True, пропустить создание брендов (только загрузить в кеш)
        skip_categories: Если True, пропустить создание категорий (только загрузить в кеш)
    """
    # Используем переданные параметры или глобальные
    api_url = api_base_url or API_BASE_URL
    db_path_local = db_path or OLD_DB_PATH
    
    if not os.path.exists(db_path_local):
        print(f"✗ Файл базы данных не найден: {db_path_local}")
        return
    
    print(f"Подключение к базе данных: {db_path_local}")
    conn = sqlite3.connect(db_path_local)
    cursor = conn.cursor()
    
    # Проверяем структуру базы
    print("\n" + "="*60)
    print("ПРОВЕРКА СТРУКТУРЫ БАЗЫ ДАННЫХ")
    print("="*60)
    structure = check_db_structure(conn)
    
    # Определяем имена таблиц (возможные варианты)
    brands_table = None
    categories_table = None
    products_table = None
    
    for table in structure.keys():
        table_lower = table.lower()
        if 'brand' in table_lower:
            brands_table = table
        elif 'categor' in table_lower:
            categories_table = table
        elif 'product' in table_lower:
            products_table = table
    
    print("\n" + "="*60)
    print("НАЧАЛО МИГРАЦИИ")
    print("="*60)
    
    # ШАГ 1: Создание брендов (или загрузка в кеш)
    if skip_brands:
        print("\n[ШАГ 1] Пропуск создания брендов (загрузка существующих в кеш)...")
        load_existing_brands(api_url)
    else:
        print("\n[ШАГ 1] Создание брендов...")
        if brands_table:
            cursor.execute(f"SELECT DISTINCT * FROM {brands_table}")
            brands = cursor.fetchall()
            brand_columns = structure[brands_table]
            
            for brand_row in brands:
                brand_dict = dict(zip(brand_columns, brand_row))
                name = brand_dict.get('name') or brand_dict.get('title') or str(brand_row[0])
                country = brand_dict.get('country') or ''
                create_brand(name, country, api_url)
                time.sleep(0.2)  # Небольшая задержка между запросами
        else:
            # Если таблицы брендов нет, попробуем найти бренды в таблице товаров
            if products_table:
                products_columns = structure[products_table]
                if 'brand' in products_columns or 'brand_name' in products_columns or 'brand_id' in products_columns:
                    brand_col = 'brand' if 'brand' in products_columns else ('brand_name' if 'brand_name' in products_columns else 'brand_id')
                    cursor.execute(f"SELECT DISTINCT {brand_col}, country FROM {products_table} WHERE {brand_col} IS NOT NULL AND {brand_col} != ''")
                    brand_rows = cursor.fetchall()
                    for brand_name, country in brand_rows:
                        if brand_name:
                            create_brand(str(brand_name), str(country) if country else '', api_url)
                            time.sleep(0.2)
    
    # ШАГ 2: Создание категорий (или загрузка в кеш)
    if skip_categories:
        print("\n[ШАГ 2] Пропуск создания категорий (загрузка существующих в кеш)...")
        load_existing_categories(api_url)
    else:
        print("\n[ШАГ 2] Создание категорий...")
        if categories_table:
            cursor.execute(f"SELECT * FROM {categories_table} ORDER BY id")
            categories = cursor.fetchall()
            category_columns = structure[categories_table]
            
            for category_row in categories:
                category_dict = dict(zip(category_columns, category_row))
                old_id = category_dict.get('id')
                name = category_dict.get('name') or category_dict.get('title') or str(category_row[0])
                parent_id = category_dict.get('parent_id')
                
                new_category_id = create_category(name, None, api_url)
                if new_category_id and old_id:
                    categories_map[old_id] = new_category_id
                time.sleep(0.2)
        else:
            # Если таблицы категорий нет, попробуем найти категории в таблице товаров
            if products_table:
                products_columns = structure[products_table]
                if 'category' in products_columns or 'category_name' in products_columns:
                    category_col = 'category' if 'category' in products_columns else 'category_name'
                    cursor.execute(f"SELECT DISTINCT {category_col} FROM {products_table} WHERE {category_col} IS NOT NULL AND {category_col} != ''")
                    category_rows = cursor.fetchall()
                    for (category_name,) in category_rows:
                        if category_name:
                            create_category(str(category_name), None, api_url)
                            time.sleep(0.2)
    
    # ШАГ 3: Создание товаров
    print("\n[ШАГ 3] Создание товаров...")
    if products_table:
        products_columns = structure[products_table]
        cursor.execute(f"SELECT * FROM {products_table}")
        products = cursor.fetchall()
        
        print(f"Найдено товаров для миграции: {len(products)}")
        
        for product_row in products:
            product_dict = dict(zip(products_columns, product_row))
            
            # Получаем данные товара
            name = product_dict.get('name') or product_dict.get('title') or product_dict.get('fullName') or ''
            article = product_dict.get('article') or product_dict.get('code') or product_dict.get('sku') or ''
            price = product_dict.get('price') or product_dict.get('cost') or product_dict.get('dilerPrice') or 0
            
            # Получаем бренд из кеша
            brand_name = product_dict.get('brand') or product_dict.get('brand_name') or ''
            brand_id = None
            if brand_name:
                # Ищем бренд в кеше по (name, country)
                country = product_dict.get('country', '')
                cache_key = (brand_name, country)
                brand_id = brands_cache.get(cache_key)
                # Если не нашли по имени+стране, пробуем найти только по имени (любая страна)
                if brand_id is None:
                    for (cached_name, cached_country), cached_id in brands_cache.items():
                        if cached_name == brand_name:
                            brand_id = cached_id
                            break
            
            # Получаем категорию
            category_id = None
            old_category_id = product_dict.get('category_id') or product_dict.get('category')
            if old_category_id and old_category_id in categories_map:
                category_id = categories_map[old_category_id]
            else:
                # Пробуем найти категорию по имени
                category_name = product_dict.get('category_name') or product_dict.get('category')
                if category_name:
                    cache_key = (category_name, None)
                    if cache_key in categories_cache:
                        category_id = categories_cache[cache_key]
                    elif not skip_categories:
                        # Создаем категорию только если не пропущено создание
                        category_id = create_category(category_name, None, api_url)
                    else:
                        # Если пропущено создание и категория не найдена, просто пропускаем
                        print(f"  ⚠ Категория '{category_name}' не найдена в базе, пропускаем привязку")
                        category_id = None
            
            # Создаем товар
            product_id = create_product(product_dict, brand_id, category_id, price, api_url)
            
            # ШАГ 4: Добавление медиа
            if product_id:
                image_url = product_dict.get('image') or product_dict.get('image_url') or product_dict.get('photo')
                if image_url:
                    add_media(product_id, str(image_url), api_url)
            
            time.sleep(0.3)  # Задержка между товарами
    
    conn.close()
    print("\n" + "="*60)
    print("МИГРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print(f"Создано брендов: {len(brands_cache)}")
    print(f"Создано категорий: {len(categories_map)}")


if __name__ == '__main__':
    print("="*60)
    print("СКРИПТ МИГРАЦИИ ДАННЫХ ИЗ products.db")
    print("="*60)
    
    # Сохраняем значения по умолчанию в локальные переменные
    # По умолчанию используем Render сервер
    default_api_url = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    default_db_path = os.path.join(os.path.dirname(__file__), 'products.db')
    
    # Обработка аргументов командной строки
    import argparse
    parser = argparse.ArgumentParser(description='Миграция данных из products.db в новую базу через API')
    parser.add_argument('--api-url', type=str, default=default_api_url,
                        help=f'URL API сервера (по умолчанию: {default_api_url})')
    parser.add_argument('--db-path', type=str, default=default_db_path,
                        help=f'Путь к файлу products.db (по умолчанию: {default_db_path})')
    parser.add_argument('--yes', action='store_true',
                        help='Запустить миграцию без подтверждения')
    parser.add_argument('--check-only', action='store_true',
                        help='Только проверить структуру базы данных, не выполнять миграцию')
    parser.add_argument('--skip-brands', action='store_true',
                        help='Пропустить создание брендов (загрузить существующие в кеш)')
    parser.add_argument('--skip-categories', action='store_true',
                        help='Пропустить создание категорий (загрузить существующие в кеш)')
    parser.add_argument('--skip-setup', action='store_true',
                        help='Пропустить создание брендов и категорий (только товары)')
    
    args = parser.parse_args()
    
    # Если указан --skip-setup, устанавливаем оба флага
    if args.skip_setup:
        args.skip_brands = True
        args.skip_categories = True
    
    # Обновляем глобальные настройки (без объявления global, так как переменные уже определены на уровне модуля)
    # Используем globals() для обновления, чтобы избежать ошибки "assigned to before global declaration"
    globals()['API_BASE_URL'] = args.api_url
    globals()['OLD_DB_PATH'] = args.db_path
    
    print(f"API URL: {API_BASE_URL}")
    print(f"База данных: {OLD_DB_PATH}")
    
    if args.check_only:
        # Только проверка структуры
        if not os.path.exists(OLD_DB_PATH):
            print(f"✗ Файл базы данных не найден: {OLD_DB_PATH}")
            sys.exit(1)
        
        conn = sqlite3.connect(OLD_DB_PATH)
        check_db_structure(conn)
        conn.close()
        sys.exit(0)
    
    # Запуск миграции
    if args.yes:
        migrate_data(API_BASE_URL, OLD_DB_PATH, args.skip_brands, args.skip_categories)
    else:
        response = input("\nНачать миграцию? (yes/no): ")
        if response.lower() in ['yes', 'y', 'да', 'д']:
            migrate_data(API_BASE_URL, OLD_DB_PATH, args.skip_brands, args.skip_categories)
        else:
            print("Миграция отменена.")

