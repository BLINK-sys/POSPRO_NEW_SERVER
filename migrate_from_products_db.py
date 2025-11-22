"""
Скрипт для миграции данных из старой базы products.db в новую базу через API.

Порядок выполнения:
1. Авторизация
2. Создание характеристик из справочника (из таблицы product_properties)
3. Создание категорий с учетом иерархии и установкой изображений
4. Создание брендов
5. Создание товаров с изображениями и характеристиками
"""

import sqlite3
import requests
import time
import os
import sys
from urllib.parse import quote, urlparse
from io import BytesIO
import unicodedata
import re

# Настройки API
# По умолчанию используем Render сервер, можно переопределить через переменную окружения или аргумент
API_BASE_URL = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
OLD_DB_PATH = os.path.join(os.path.dirname(__file__), 'products.db')

# JWT токен для авторизации
JWT_TOKEN = None

# Словари для маппинга старых ID на новые
brands_map = {}  # {old_brand_id: new_brand_id}
categories_map = {}  # {old_category_id: new_category_id}
brands_cache = {}  # {(name, country): brand_id} для быстрого поиска
categories_cache = {}  # {(name, parent_id): category_id} для быстрого поиска
characteristics_cache = {}  # {characteristic_key: characteristic_id} для быстрого поиска
products_cache = {}  # {name: product_id} для быстрого поиска товаров
existing_brands_loaded = False  # Флаг загрузки существующих брендов
existing_categories_loaded = False  # Флаг загрузки существующих категорий
existing_characteristics_loaded = False  # Флаг загрузки существующих характеристик
existing_products_loaded = False  # Флаг загрузки существующих товаров


def get_auth_headers():
    """Получает заголовки авторизации с JWT токеном"""
    headers = {'Content-Type': 'application/json'}
    if JWT_TOKEN:
        headers['Authorization'] = f'Bearer {JWT_TOKEN}'
    return headers


def login(api_url, email='bocan.anton@mail.ru', password='1'):
    """Авторизация и получение JWT токена"""
    global JWT_TOKEN
    
    login_url = f"{api_url.replace('/api', '')}/auth/login" if '/api' in api_url else f"{api_url}/auth/login"
    try:
        response = requests.post(
            login_url,
            json={'email': email, 'password': password},
            headers={'Content-Type': 'application/json'},
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            JWT_TOKEN = data.get('token')
            print(f"✓ Успешная авторизация")
            return True
        else:
            print(f"✗ Ошибка авторизации: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"✗ Ошибка при авторизации: {e}")
        return False


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


def load_existing_characteristics(api_url):
    """Загружает все существующие характеристики в кеш"""
    global existing_characteristics_loaded, characteristics_cache
    
    if existing_characteristics_loaded:
        return
    
    characteristics_url = normalize_url(api_url, 'characteristics-list')
    print(f"  Загрузка существующих характеристик с {characteristics_url}...")
    try:
        response = requests.get(characteristics_url, headers=get_auth_headers(), timeout=60)
        if response.status_code == 200:
            result = response.json()
            if result.get('success') and result.get('data'):
                for char in result['data']:
                    key = char.get('characteristic_key', '')
                    if key:
                        characteristics_cache[key] = char['id']
                existing_characteristics_loaded = True
                print(f"  ✓ Загружено {len(characteristics_cache)} существующих характеристик в кеш")
            else:
                print(f"  ⚠ Неожиданный формат ответа")
        else:
            print(f"  ⚠ Ошибка загрузки характеристик: {response.status_code}")
    except requests.exceptions.Timeout:
        print(f"  ⚠ Таймаут при загрузке характеристик (сервер может быть в режиме сна)")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке существующих характеристик: {e}")


def create_characteristic(key, api_url=None):
    """Создает характеристику через API с проверкой на дубликаты"""
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    # Загружаем существующие характеристики при первом вызове
    load_existing_characteristics(api_url)
    
    # Проверяем кеш
    if key in characteristics_cache:
        existing_id = characteristics_cache[key]
        print(f"  ✓ Характеристика '{key}' уже существует (ID: {existing_id}), пропускаем")
        return existing_id
    
    # Создаем новую характеристику
    characteristics_url = normalize_url(api_url, 'characteristics-list')
    try:
        data = {
            'characteristic_key': key.strip()
        }
        response = requests.post(
            characteristics_url,
            json=data,
            headers=get_auth_headers(),
            timeout=60
        )
        
        if response.status_code == 201:
            result = response.json()
            if result.get('success') and result.get('data'):
                char_id = result['data'].get('id')
                characteristics_cache[key] = char_id
                print(f"✓ Создана характеристика: {key} (ID: {char_id})")
                return char_id
        elif response.status_code == 400:
            # Может быть дубликат
            result = response.json()
            if 'уже существует' in result.get('message', '').lower() or 'already exists' in result.get('message', '').lower():
                print(f"  ✓ Характеристика '{key}' уже существует, пропускаем")
                # Попробуем загрузить снова и найти
                load_existing_characteristics(api_url)
                if key in characteristics_cache:
                    return characteristics_cache[key]
        print(f"✗ Ошибка создания характеристики {key}: {response.status_code} - {response.text}")
        return None
    except Exception as e:
        print(f"✗ Ошибка при создании характеристики {key}: {e}")
        return None


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
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            brand_id = result.get('id')
            brands_cache[cache_key] = brand_id
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


def get_category_info(category_id, api_url):
    """Получает информацию о категории через API"""
    try:
        category_url = normalize_url(api_url, f'categories/{category_id}')
        response = requests.get(
            category_url,
            headers=get_auth_headers(),
            timeout=60
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"  ⚠ Ошибка при получении информации о категории {category_id}: {e}")
        return None


def upload_category_image_from_url(category_id, image_url, api_url):
    """Загружает изображение категории по URL, если у категории еще нет изображения"""
    if not image_url or not category_id:
        return False
    
    # Проверяем есть ли уже изображение у категории
    category_info = get_category_info(category_id, api_url)
    if category_info:
        existing_image_url = category_info.get('image_url')
        if existing_image_url and existing_image_url.strip():
            # У категории уже есть изображение
            print(f"  ℹ У категории {category_id} уже есть изображение: {existing_image_url}, пропускаем загрузку")
            return True
    
    # Проверяем тип URL изображения
    image_url = str(image_url).strip()
    
    # Если это локальное изображение (уже на сервере), просто пропускаем
    if image_url.startswith('/uploads/categories/'):
        print(f"  ℹ Локальное изображение категории, пропускаем: {image_url}")
        return True
    
    # Если это внешнее изображение - скачиваем и загружаем
    if not (image_url.startswith('http://') or image_url.startswith('https://')):
        print(f"  ⚠ Неизвестный формат URL изображения категории: {image_url}")
        return False
    
    try:
        print(f"  🔄 Скачивание и загрузка изображения категории: {image_url}")
        # Скачиваем изображение
        img_response = requests.get(image_url, timeout=30, stream=True)
        if img_response.status_code != 200:
            print(f"  ⚠ Не удалось скачать изображение {image_url}: {img_response.status_code}")
            return False
        
        # Определяем имя файла
        parsed_url = urlparse(image_url)
        filename = os.path.basename(parsed_url.path) or 'image.jpg'
        
        # Загружаем на сервер
        upload_url = normalize_url(api_url, f'upload/category/{category_id}')
        files = {'file': (filename, img_response.content, img_response.headers.get('Content-Type', 'image/jpeg'))}
        
        response = requests.post(
            upload_url,
            files=files,
            headers={'Authorization': f'Bearer {JWT_TOKEN}'} if JWT_TOKEN else {},
            timeout=60
        )
        
        if response.status_code == 200:
            print(f"  ✓ Загружено изображение для категории {category_id}")
            return True
        else:
            print(f"  ⚠ Ошибка загрузки изображения: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"  ⚠ Ошибка при загрузке изображения категории: {e}")
        return False


def create_category(name, parent_id=None, image_url=None, api_url=None):
    """Создает категорию через API с проверкой на дубликаты и установкой изображения"""
    if not name:
        return None
    
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    # Загружаем существующие категории при первом вызове
    load_existing_categories(api_url)
    
    # Проверяем кеш
    cache_key = (name, parent_id)
    if cache_key in categories_cache:
        existing_id = categories_cache[cache_key]
        print(f"  ✓ Категория '{name}' уже существует (ID: {existing_id})")
        # Если есть изображение, проверяем и загружаем только если его еще нет
        if image_url:
            upload_category_image_from_url(existing_id, image_url, api_url)
        return existing_id
    
    # Генерируем slug
    slug = safe_slugify(name)
    if not slug:
        slug = f"category-{int(time.time())}"
    
    try:
        # Создаем категорию через multipart/form-data
        data = {
            'name': name,
            'slug': slug,
            'description': '',
            'parent_id': str(parent_id) if parent_id else ''
        }
        categories_url = normalize_url(api_url, 'categories/with-image')
        response = requests.post(
            categories_url,
            data=data,
            timeout=60
        )
        
        if response.status_code == 201:
            result = response.json()
            category_id = result.get('id')
            categories_cache[cache_key] = category_id
            print(f"✓ Создана категория: {name} (ID: {category_id})")
            
            # Загружаем изображение, если есть
            if image_url:
                upload_category_image_from_url(category_id, image_url, api_url)
            
            return category_id
        else:
            print(f"✗ Ошибка создания категории {name}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"✗ Ошибка при создании категории {name}: {e}")
        return None


def load_existing_products(api_url):
    """Загружает все существующие товары в кеш порционно (по имени для проверки дубликатов)"""
    global existing_products_loaded, products_cache
    
    if existing_products_loaded:
        return
    
    # Инициализируем кеш только при первой загрузке
    products_cache = {}  # {name: product_id} для быстрого поиска
    
    products_url = normalize_url(api_url, 'products/')
    print(f"  Загрузка существующих товаров с {products_url} (порционно)...")
    
    per_page = 200  # Максимальное количество товаров за запрос
    page = 1
    total_loaded = 0
    
    try:
        while True:
            params = {
                'per_page': per_page,
                'page': page
            }
            
            response = requests.get(
                products_url, 
                params=params,
                headers=get_auth_headers(),
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Проверяем формат ответа
                if isinstance(data, list):
                    # Без пагинации - возвращается список
                    existing_products = data
                    has_more = len(existing_products) == per_page
                elif isinstance(data, dict) and 'products' in data:
                    # С пагинацией - возвращается объект с полем products
                    existing_products = data.get('products', [])
                    total_pages = data.get('total_pages', 1)
                    has_more = page < total_pages
                else:
                    print(f"  ⚠ Неожиданный формат ответа API")
                    break
                
                # Добавляем товары в кеш
                for product in existing_products:
                    name = product.get('name', '').strip()
                    if name:
                        products_cache[name] = product['id']
                
                loaded_count = len(existing_products)
                total_loaded += loaded_count
                
                print(f"  Загружено страница {page}: {loaded_count} товаров (всего в кеше: {len(products_cache)})")
                
                # Если товаров меньше чем per_page, значит это последняя страница
                if not has_more or loaded_count < per_page:
                    break
                
                page += 1
                time.sleep(0.2)  # Небольшая задержка между запросами
            else:
                print(f"  ⚠ Ошибка загрузки товаров: {response.status_code}")
                break
                
        existing_products_loaded = True
        print(f"  ✓ Загружено {total_loaded} существующих товаров в кеш (уникальных имен: {len(products_cache)})")
        
    except requests.exceptions.Timeout:
        print(f"  ⚠ Таймаут при загрузке товаров (сервер может быть в режиме сна)")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке существующих товаров: {e}")
        import traceback
        traceback.print_exc()


def is_external_url(url):
    """Проверяет, является ли URL внешним (начинается с http:// или https://)"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return url.startswith('http://') or url.startswith('https://')


def is_local_url(url):
    """Проверяет, является ли URL локальным (начинается с /uploads/products/)"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return url.startswith('/uploads/products/')


def sanitize_filename(filename):
    """Очищает имя файла от опасных символов"""
    if not filename:
        return 'image.jpg'
    
    # Получаем имя файла из URL
    parsed = urlparse(filename)
    filename = os.path.basename(parsed.path) or 'image.jpg'
    
    # Убираем query параметры если есть
    if '?' in filename:
        filename = filename.split('?')[0]
    if '#' in filename:
        filename = filename.split('#')[0]
    
    # Заменяем пробелы на подчеркивания
    filename = filename.replace(' ', '_')
    
    # Убираем опасные символы, но оставляем кириллицу и латиницу
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    
    # Если имя файла пустое или нет расширения, добавляем .jpg
    if not filename or '.' not in filename:
        # Генерируем уникальное имя на основе timestamp
        timestamp = int(time.time() * 1000) % 1000000
        filename = f'image_{timestamp}.jpg'
    else:
        # Проверяем расширение - должно быть изображение
        ext = filename.lower().split('.')[-1]
        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        if ext not in allowed_extensions:
            # Если расширение не подходит, заменяем на .jpg
            base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
            # Очищаем базовое имя от опасных символов еще раз
            base_name = re.sub(r'[<>:"/\\|?*]', '', base_name)
            if not base_name:
                base_name = 'image'
            filename = f'{base_name}.jpg'
    
    return filename


def is_valid_image(content):
    """Проверяет что содержимое является валидным изображением по сигнатуре"""
    if not content or len(content) < 4:
        return False
    
    # Проверяем сигнатуры популярных форматов изображений
    signatures = {
        b'\xFF\xD8\xFF': 'jpg',  # JPEG
        b'\x89\x50\x4E\x47': 'png',  # PNG
        b'GIF87a': 'gif',  # GIF87a
        b'GIF89a': 'gif',  # GIF89a
        b'RIFF': 'webp',  # WebP (нужна дополнительная проверка)
    }
    
    # Проверяем первые байты
    for sig, fmt in signatures.items():
        if content.startswith(sig):
            return True
    
    # Для WebP проверяем что после RIFF идет WEBP
    if content.startswith(b'RIFF') and b'WEBP' in content[:12]:
        return True
    
    return False


def download_image(image_url):
    """Скачивает изображение по URL и возвращает содержимое и имя файла"""
    try:
        print(f"    Скачивание изображения: {image_url}")
        response = requests.get(image_url, timeout=30, stream=True)
        
        if response.status_code != 200:
            print(f"    ⚠ Не удалось скачать изображение: {response.status_code}")
            return None, None
        
        # Читаем содержимое
        content = response.content
        
        # Проверяем размер (максимум 20MB)
        if len(content) > 20 * 1024 * 1024:
            print(f"    ⚠ Изображение слишком большое: {len(content)} bytes")
            return None, None
        
        # Проверяем что это действительно изображение
        if not is_valid_image(content):
            print(f"    ⚠ Скачанный файл не является валидным изображением")
            return None, None
        
        # Определяем имя файла
        content_disposition = response.headers.get('Content-Disposition', '')
        if 'filename=' in content_disposition:
            filename = content_disposition.split('filename=')[1].strip('"\'')
        else:
            filename = sanitize_filename(image_url)
        
        print(f"    ✓ Изображение скачано: {len(content)} bytes, имя: {filename}")
        return content, filename
        
    except requests.exceptions.Timeout:
        print(f"    ⚠ Таймаут при скачивании изображения")
        return None, None
    except Exception as e:
        print(f"    ⚠ Ошибка при скачивании изображения: {e}")
        return None, None


def get_content_type_from_filename(filename):
    """Определяет Content-Type на основе расширения файла"""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    content_types = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    return content_types.get(ext, 'image/jpeg')


def upload_product_image_file(product_id, image_content, filename, api_url):
    """Загружает изображение товара на сервер через API как файл"""
    try:
        upload_url = normalize_url(api_url, 'upload/upload_product')
        
        # Определяем Content-Type на основе расширения
        content_type = get_content_type_from_filename(filename)
        
        # Подготавливаем multipart/form-data
        files = {
            'file': (filename, image_content, content_type)
        }
        data = {
            'product_id': str(product_id)
        }
        
        headers = {}
        if JWT_TOKEN:
            headers['Authorization'] = f'Bearer {JWT_TOKEN}'
        
        response = requests.post(
            upload_url,
            files=files,
            data=data,
            headers=headers,
            timeout=120  # Увеличенный таймаут для больших файлов
        )
        
        if response.status_code == 200:
            result = response.json()
            new_url = result.get('url')
            media_id = result.get('id')
            print(f"  ✓ Изображение загружено на сервер: {new_url}")
            return True
        else:
            print(f"  ✗ Ошибка загрузки изображения: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке изображения: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_product_media(product_id, api_url):
    """Получает все медиафайлы товара через API"""
    try:
        media_url = normalize_url(api_url, f'upload/media/{product_id}')
        
        response = requests.get(
            media_url,
            headers=get_auth_headers(),
            timeout=60
        )
        
        if response.status_code == 200:
            media_list = response.json()
            if isinstance(media_list, list):
                return media_list
            else:
                return []
        else:
            return []
            
    except Exception as e:
        print(f"  ⚠ Ошибка при получении медиа товара {product_id}: {e}")
        return []


def add_product_image(product_id, image_url, api_url):
    """Добавляет изображение товара по URL. Если URL внешний - скачивает и загружает на сервер"""
    if not image_url or not product_id:
        return False
    
    image_url = str(image_url).strip()
    
    # Проверяем существующие медиа товара
    existing_media = get_product_media(product_id, api_url)
    existing_urls = {m.get('url', '').strip() for m in existing_media if m.get('media_type') == 'image'}
    
    # Проверяем тип URL
    if is_local_url(image_url):
        # Проверяем, не существует ли уже это изображение
        if image_url in existing_urls:
            print(f"  ℹ Локальное изображение уже существует для товара {product_id}: {image_url}")
            return True
            
        # Локальное изображение - просто добавляем URL в БД
        print(f"  ℹ Локальное изображение, добавляем URL: {image_url}")
        try:
            upload_url = normalize_url(api_url, f'upload/media/{product_id}')
            data = {
                'url': image_url,
                'media_type': 'image'
            }
            response = requests.post(
                upload_url,
                json=data,
                headers=get_auth_headers(),
                timeout=60
            )
            
            if response.status_code == 201:
                print(f"  ✓ Добавлено локальное изображение для товара {product_id}")
                return True
            elif response.status_code == 409 or "already exists" in response.text.lower():
                print(f"  ℹ Локальное изображение {image_url} уже существует для товара {product_id}")
                return True
            else:
                print(f"  ⚠ Ошибка добавления локального изображения: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"  ⚠ Ошибка при добавлении локального изображения: {e}")
            return False
    
    elif is_external_url(image_url):
        # Для внешних URL определяем имя файла и проверяем, не загружено ли уже изображение с таким именем
        # После скачивания URL изменится на локальный, поэтому проверяем по имени файла
        filename = sanitize_filename(image_url)
        expected_local_url = f'/uploads/products/{product_id}/{filename}'
        
        # Проверяем, не существует ли уже локальное изображение с таким именем
        if expected_local_url in existing_urls:
            print(f"  ℹ Изображение уже загружено для товара {product_id}: {expected_local_url}")
            return True
        
        # Внешнее изображение - скачиваем и загружаем на сервер
        print(f"  🔄 Внешнее изображение, скачиваем и загружаем: {image_url}")
        
        # Скачиваем изображение
        image_content, filename = download_image(image_url)
        
        if not image_content or not filename:
            print(f"  ✗ Не удалось скачать изображение")
            return False
        
        # Проверяем еще раз после получения реального имени файла
        final_local_url = f'/uploads/products/{product_id}/{filename}'
        if final_local_url in existing_urls:
            print(f"  ℹ Изображение уже загружено для товара {product_id}: {final_local_url}")
            return True
        
        # Загружаем на сервер
        success = upload_product_image_file(product_id, image_content, filename, api_url)
        return success
    
    else:
        # Неизвестный формат URL
        print(f"  ⚠ Неизвестный формат URL изображения: {image_url}")
        return False


def add_product_characteristic(product_id, characteristic_id, value, api_url):
    """Добавляет характеристику товару"""
    if not product_id or not characteristic_id:
        return False
    
    try:
        characteristics_url = normalize_url(api_url, f'characteristics/{product_id}')
        data = {
            'characteristic_id': characteristic_id,
            'value': str(value) if value else ''
        }
        response = requests.post(
            characteristics_url,
            json=data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {JWT_TOKEN}'} if JWT_TOKEN else {'Content-Type': 'application/json'},
            timeout=60
        )
        
        if response.status_code == 201:
            return True
        else:
            print(f"  ⚠ Ошибка добавления характеристики: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"  ⚠ Ошибка при добавлении характеристики товара: {e}")
        return False


def create_product(product_data, old_brand_id, old_category_id, api_url=None):
    """Создает товар через API с проверкой на дубликаты"""
    if api_url is None:
        api_url = globals().get('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    
    # Загружаем существующие товары при первом вызове
    load_existing_products(api_url)
    
    # Получаем данные товара
    name = product_data.get('name') or product_data.get('fullName', '').strip()
    if not name:
        print(f"  ⚠ Товар без имени, пропускаем")
        return None
    
    # Получаем остальные данные для обновления
    in_stock = product_data.get('inStock', 0)
    # Обрабатываем inStock - может быть число или строка
    try:
        quantity = int(in_stock) if in_stock else 0
    except (ValueError, TypeError):
        quantity = 0
    
    description = product_data.get('description', '') or ''
    price = product_data.get('price', 0) or 0
    
    # Проверяем на дубликат по имени
    if name in products_cache:
        existing_id = products_cache[name]
        print(f"  ✓ Товар '{name}' уже существует (ID: {existing_id}), обновляем цену и остатки")
        
        # Обновляем цену и остатки для существующего товара
        try:
            update_data = {
                'price': float(price) if price else 0,
                'quantity': quantity
            }
            products_url = normalize_url(api_url, f'products/{existing_id}')
            response = requests.put(
                products_url,
                json=update_data,
                headers=get_auth_headers(),
                timeout=60
            )
            
            if response.status_code == 200:
                print(f"  ✓ Обновлены цена и остатки для товара '{name}' (ID: {existing_id})")
            else:
                print(f"  ⚠ Не удалось обновить товар '{name}': {response.status_code} - {response.text[:200]}")
        except Exception as e:
            print(f"  ⚠ Ошибка при обновлении товара '{name}': {e}")
        
        # Изображение будет обработано в основном цикле миграции
        return existing_id
    
    # Получаем новый brand_id по старому ID
    new_brand_id = None
    if old_brand_id and old_brand_id in brands_map:
        new_brand_id = brands_map[old_brand_id]
    
    # Получаем новый category_id по старому ID
    new_category_id = None
    if old_category_id and old_category_id in categories_map:
        new_category_id = categories_map[old_category_id]
    
    # Генерируем артикул на основе имени
    import hashlib
    name_hash = hashlib.md5(name.encode('utf-8')).hexdigest()[:8].upper()
    timestamp = int(time.time() * 1000) % 1000000
    article = f"MIGR-{name_hash}-{timestamp}"
    
    try:
        data = {
            'name': name,
            'article': article,
            'price': float(price) if price else 0,
            'wholesale_price': 0,
            'quantity': quantity,
            'status': None,
            'is_visible': True,
            'country': '',
            'brand_id': new_brand_id,  # Используем только brand_id
            'description': description,
            'category_id': new_category_id
        }
        products_url = normalize_url(api_url, 'products/')
        response = requests.post(
            products_url,
            json=data,
            headers=get_auth_headers(),
            timeout=60
        )
        
        if response.status_code == 201:
            result = response.json()
            product_id = result.get('id')
            products_cache[name] = product_id
            print(f"✓ Создан товар: {name} (ID: {product_id})")
            return product_id
        else:
            error_text = response.text
            if 'UniqueViolation' in error_text or 'product_article_key' in error_text or 'duplicate key' in error_text.lower():
                print(f"  ⚠ Товар '{name}' уже существует (ошибка уникальности), пропускаем")
                return None
            print(f"✗ Ошибка создания товара {name}: {response.status_code} - {error_text[:200]}")
            return None
    except Exception as e:
        print(f"✗ Ошибка при создании товара {name}: {e}")
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


def migrate_data(api_base_url=None, db_path=None):
    """
    Основная функция миграции
    
    Порядок выполнения:
    1. Авторизация
    2. Создание характеристик из справочника (из таблицы product_properties)
    3. Создание категорий с учетом иерархии и установкой изображений
    4. Создание брендов
    5. Создание товаров с изображениями и характеристиками
    
    Args:
        api_base_url: URL API сервера
        db_path: Путь к файлу products.db
    """
    # Используем переданные параметры или глобальные
    api_url = api_base_url or API_BASE_URL
    db_path_local = db_path or OLD_DB_PATH
    
    if not os.path.exists(db_path_local):
        print(f"✗ Файл базы данных не найден: {db_path_local}")
        return
    
    # Авторизация
    print("\n" + "="*60)
    print("АВТОРИЗАЦИЯ")
    print("="*60)
    if not login(api_url):
        print("✗ Не удалось авторизоваться. Миграция прервана.")
        return
    
    print(f"Подключение к базе данных: {db_path_local}")
    conn = sqlite3.connect(db_path_local)
    cursor = conn.cursor()
    
    # Проверяем структуру базы
    print("\n" + "="*60)
    print("ПРОВЕРКА СТРУКТУРЫ БАЗЫ ДАННЫХ")
    print("="*60)
    structure = check_db_structure(conn)
    
    # Определяем имена таблиц
    brands_table = None
    categories_table = None
    product_properties_table = None
    
    for table in structure.keys():
        table_lower = table.lower()
        if 'brand' in table_lower:
            brands_table = table
        elif 'categor' in table_lower:
            categories_table = table
        elif 'product_propert' in table_lower or 'property' in table_lower:
            product_properties_table = table
    
    print("\n" + "="*60)
    print("НАЧАЛО МИГРАЦИИ")
    print("="*60)
    
    # ШАГ 1: Создание характеристик из справочника
    print("\n[ШАГ 1] Создание характеристик из справочника...")
    if product_properties_table:
        properties_columns = structure[product_properties_table]
        # Получаем уникальные имена характеристик
        if 'property_name' in properties_columns:
            cursor.execute(f"SELECT DISTINCT property_name FROM {product_properties_table} WHERE property_name IS NOT NULL AND property_name != ''")
            unique_properties = [row[0] for row in cursor.fetchall()]
            print(f"Найдено уникальных характеристик: {len(unique_properties)}")
            
            for prop_name in unique_properties:
                if prop_name and prop_name.strip():
                    create_characteristic(prop_name.strip(), api_url)
                    time.sleep(0.2)  # Небольшая задержка между запросами
        else:
            print(f"  ⚠ В таблице {product_properties_table} не найдено поле property_name")
    else:
        print(f"  ⚠ Таблица product_properties не найдена")
    
    # ШАГ 2: Создание категорий с учетом иерархии
    print("\n[ШАГ 2] Создание категорий с учетом иерархии...")
    if categories_table:
        category_columns = structure[categories_table]
        
        # Сначала получаем все категории
        cursor.execute(f"SELECT * FROM {categories_table} ORDER BY id")
        all_categories = cursor.fetchall()
        
        print(f"Найдено категорий в старой БД: {len(all_categories)}")
        
        # Создаем словарь категорий по ID
        categories_dict = {}
        for cat_row in all_categories:
            cat_dict = dict(zip(category_columns, cat_row))
            old_id = cat_dict.get('id')
            categories_dict[old_id] = cat_dict
        
        # Функция для рекурсивного создания категорий
        processed_count = [0]  # Используем список для изменения в замыкании
        
        def create_category_recursive(old_cat_id, parent_new_id=None):
            if old_cat_id not in categories_dict:
                return None
            
            cat_dict = categories_dict[old_cat_id]
            name = cat_dict.get('name', '').strip()
            if not name:
                return None
            
            # Проверяем, не обработана ли уже категория с этим old_id
            if old_cat_id in categories_map:
                # Категория уже была обработана, используем сохраненный ID
                new_category_id = categories_map[old_cat_id]
                # Не выводим сообщение для уже обработанных, чтобы не засорять лог
            else:
                processed_count[0] += 1
                # Получаем изображение
                image_url = cat_dict.get('img') or cat_dict.get('image') or cat_dict.get('image_url')
                
                # Создаем категорию (функция create_category сама проверяет кеш и выводит сообщения)
                new_category_id = create_category(name, parent_new_id, image_url, api_url)
                if new_category_id:
                    categories_map[old_cat_id] = new_category_id
                    time.sleep(0.2)
                else:
                    # Если категория уже существовала в кеше, create_category вернет её ID
                    # Но нужно сохранить маппинг для old_id
                    cache_key = (name, parent_new_id)
                    if cache_key in categories_cache:
                        new_category_id = categories_cache[cache_key]
                        categories_map[old_cat_id] = new_category_id
            
            # Рекурсивно создаем дочерние категории (даже если категория уже существовала)
            if new_category_id:
                for child_old_id, child_dict in categories_dict.items():
                    if child_dict.get('parent_id') == old_cat_id:
                        create_category_recursive(child_old_id, new_category_id)
            
            return new_category_id
        
        # Создаем категории без родителя (основные)
        root_categories_count = 0
        for old_id, cat_dict in categories_dict.items():
            if not cat_dict.get('parent_id'):
                root_categories_count += 1
                create_category_recursive(old_id, None)
        
        print(f"Обработано корневых категорий: {root_categories_count}")
        print(f"Всего обработано категорий: {processed_count[0]}")
        print(f"Создано/найдено категорий: {len(categories_map)}")
    else:
        print(f"  ⚠ Таблица categories не найдена")
    
    # ШАГ 3: Создание брендов
    print("\n[ШАГ 3] Создание брендов...")
    if brands_table:
        brand_columns = structure[brands_table]
        cursor.execute(f"SELECT * FROM {brands_table}")
        brands = cursor.fetchall()
        
        for brand_row in brands:
            brand_dict = dict(zip(brand_columns, brand_row))
            name = brand_dict.get('brand') or brand_dict.get('name') or ''
            country = brand_dict.get('country') or ''
            
            if name and name.strip():
                old_id = brand_dict.get('id')
                new_id = create_brand(name.strip(), country, api_url)
                if new_id and old_id:
                    brands_map[old_id] = new_id
                time.sleep(0.2)
    else:
        print(f"  ⚠ Таблица brands не найдена")
    
    # ШАГ 4: Создание товаров
    print("\n[ШАГ 4] Создание товаров с изображениями...")
    products_table = None
    for table in structure.keys():
        table_lower = table.lower()
        if 'product' in table_lower and 'property' not in table_lower:
            products_table = table
            break
    
    if products_table:
        products_columns = structure[products_table]
        cursor.execute(f"SELECT * FROM {products_table}")
        products = cursor.fetchall()
        
        print(f"Найдено товаров для миграции: {len(products)}")
        
        for product_row in products:
            product_dict = dict(zip(products_columns, product_row))
            
            # Получаем старые ID
            old_brand_id = product_dict.get('brand_id')
            old_category_id = product_dict.get('category_id')
            
            # Создаем товар
            product_id = create_product(product_dict, old_brand_id, old_category_id, api_url)
            
            if product_id:
                # Добавляем изображение
                image_url = product_dict.get('img') or product_dict.get('image') or product_dict.get('image_url')
                if image_url:
                    add_product_image(product_id, str(image_url), api_url)
                    time.sleep(0.1)
                
                # Добавляем характеристики из product_properties
                if product_properties_table:
                    properties_columns = structure[product_properties_table]
                    cursor.execute(f"SELECT * FROM {product_properties_table} WHERE product_id = ?", (product_dict.get('id'),))
                    properties = cursor.fetchall()
                    
                    for prop_row in properties:
                        prop_dict = dict(zip(properties_columns, prop_row))
                        property_name = prop_dict.get('property_name', '').strip()
                        property_value = prop_dict.get('property_value', '')
                        
                        if property_name and property_name in characteristics_cache:
                            characteristic_id = characteristics_cache[property_name]
                            add_product_characteristic(product_id, characteristic_id, property_value, api_url)
                            time.sleep(0.1)
            
            time.sleep(0.2)  # Задержка между товарами
    else:
        print(f"  ⚠ Таблица products не найдена")
    
    conn.close()
    print("\n" + "="*60)
    print("МИГРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print(f"Характеристики: {len(characteristics_cache)}")
    print(f"Категории: {len(categories_map)}")
    print(f"Бренды: {len(brands_map)}")
    print(f"Обработано товаров: {len(products_cache)}")


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
    parser = argparse.ArgumentParser(description='Миграция характеристик, категорий и брендов из products.db в новую базу через API')
    parser.add_argument('--api-url', type=str, default=default_api_url,
                        help=f'URL API сервера (по умолчанию: {default_api_url})')
    parser.add_argument('--db-path', type=str, default=default_db_path,
                        help=f'Путь к файлу products.db (по умолчанию: {default_db_path})')
    parser.add_argument('--yes', action='store_true',
                        help='Запустить миграцию без подтверждения')
    parser.add_argument('--check-only', action='store_true',
                        help='Только проверить структуру базы данных, не выполнять миграцию')
    
    args = parser.parse_args()
    
    # Обновляем глобальные настройки
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
        migrate_data(API_BASE_URL, OLD_DB_PATH)
    else:
        response = input("\nНачать миграцию? (yes/no): ")
        if response.lower() in ['yes', 'y', 'да', 'д']:
            migrate_data(API_BASE_URL, OLD_DB_PATH)
        else:
            print("Миграция отменена.")

