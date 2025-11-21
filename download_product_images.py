"""
Скрипт для скачивания внешних изображений товаров на сервер.

Проверяет все изображения товаров и если URL начинается с http:// или https://,
скачивает изображение и загружает его на сервер в правильную папку товара.

Для тестирования ограничен до 10 товаров.
"""

import requests
import time
import os
import sys
from urllib.parse import urlparse
from io import BytesIO
import re

# Настройки API
API_BASE_URL = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')

# JWT токен для авторизации
JWT_TOKEN = None

# Статистика
stats = {
    'products_processed': 0,
    'images_checked': 0,
    'images_downloaded': 0,
    'images_skipped': 0,
    'errors': 0
}

# Ограничение для теста
TEST_LIMIT = 10  # Обработать только первые 10 товаров


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
        
        # Проверяем Content-Type для информации
        content_type = response.headers.get('Content-Type', '')
        if 'image' not in content_type.lower() and content_type:
            print(f"    ⚠ Неожиданный Content-Type: {content_type}, но файл валидный")
        
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


def upload_product_image(product_id, image_content, filename, api_url):
    """Загружает изображение товара на сервер через API"""
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
        
        print(f"    Загрузка изображения на сервер для товара {product_id}...")
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
            print(f"    ✓ Изображение загружено: {new_url} (ID: {media_id})")
            return media_id, new_url
        else:
            print(f"    ✗ Ошибка загрузки изображения: {response.status_code} - {response.text}")
            return None, None
            
    except Exception as e:
        print(f"    ✗ Ошибка при загрузке изображения: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def delete_media(media_id, api_url):
    """Удаляет запись медиа через API"""
    try:
        delete_url = normalize_url(api_url, f'upload/media/{media_id}')
        
        headers = {}
        if JWT_TOKEN:
            headers['Authorization'] = f'Bearer {JWT_TOKEN}'
        
        response = requests.delete(
            delete_url,
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            print(f"    ✓ Старая запись медиа удалена (ID: {media_id})")
            return True
        else:
            print(f"    ⚠ Ошибка удаления старой записи: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"    ⚠ Ошибка при удалении старой записи: {e}")
        return False


def update_media_order(media_id, order, product_id, api_url):
    """Обновляет порядок медиа через API reorder"""
    # Для простоты используем reorder endpoint
    # Это не критично, если не получится - просто порядок будет по умолчанию
    try:
        reorder_url = normalize_url(api_url, f'upload/media/reorder/{product_id}')
        
        headers = {'Content-Type': 'application/json'}
        if JWT_TOKEN:
            headers['Authorization'] = f'Bearer {JWT_TOKEN}'
        
        # Отправляем список с одним элементом для обновления order
        data = [{'id': media_id, 'order': order}]
        
        response = requests.post(
            reorder_url,
            json=data,
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            return True
        else:
            # Если не получилось, не критично - просто не обновим order
            return False
            
    except Exception as e:
        # Не критично, просто пропускаем обновление order
        return False


def get_all_products(api_url, limit=None):
    """Получает список всех товаров через API"""
    try:
        products_url = normalize_url(api_url, 'products/')
        
        # Запрашиваем с пагинацией если указан лимит
        params = {}
        if limit:
            params['per_page'] = limit
            params['page'] = 1
        # Если лимит не указан, не передаем per_page чтобы получить все товары
        
        response = requests.get(
            products_url,
            params=params if params else None,
            headers=get_auth_headers(),
            timeout=120
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Проверяем формат ответа
            if isinstance(data, list):
                # Без пагинации - возвращается список
                products = data
            elif isinstance(data, dict) and 'products' in data:
                # С пагинацией - возвращается объект с полем products
                products = data['products']
            else:
                print(f"✗ Неожиданный формат ответа API: {type(data)}")
                return []
            
            # Ограничиваем количество если нужно
            if limit and len(products) > limit:
                products = products[:limit]
            
            print(f"✓ Получено товаров: {len(products)}")
            return products
        else:
            print(f"✗ Ошибка получения товаров: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        print(f"✗ Ошибка при получении товаров: {e}")
        import traceback
        traceback.print_exc()
        return []


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
            print(f"    ⚠ Ошибка получения медиа: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"    ⚠ Ошибка при получении медиа: {e}")
        return []


def process_product_images(product, api_url):
    """Обрабатывает изображения одного товара"""
    product_id = product.get('id')
    product_name = product.get('name', 'Unknown')
    
    if not product_id:
        print(f"  ⚠ Товар без ID, пропускаем")
        return
    
    print(f"\n[{stats['products_processed'] + 1}] Обработка товара ID: {product_id}, название: {product_name}")
    
    # Получаем медиа товара
    media_list = get_product_media(product_id, api_url)
    
    if not media_list:
        print(f"  ℹ Нет медиафайлов для товара {product_id}")
        stats['products_processed'] += 1
        return
    
    # Фильтруем только изображения
    images = [m for m in media_list if m.get('media_type') == 'image']
    
    if not images:
        print(f"  ℹ Нет изображений для товара {product_id}")
        stats['products_processed'] += 1
        return
    
    print(f"  Найдено изображений: {len(images)}")
    
    # Обрабатываем каждое изображение
    for media in images:
        media_id = media.get('id')
        image_url = media.get('url', '').strip()
        media_order = media.get('order', 0)
        
        stats['images_checked'] += 1
        
        if not image_url:
            print(f"    ⚠ Пустой URL для медиа ID: {media_id}")
            continue
        
        # Проверяем тип URL
        if is_local_url(image_url):
            print(f"    ✓ Локальное изображение, пропускаем: {image_url}")
            stats['images_skipped'] += 1
            continue
        
        if not is_external_url(image_url):
            print(f"    ⚠ Неизвестный формат URL: {image_url}")
            stats['images_skipped'] += 1
            continue
        
        # Это внешнее изображение - нужно скачать
        print(f"    🔄 Внешнее изображение: {image_url}")
        
        # Скачиваем изображение
        image_content, filename = download_image(image_url)
        
        if not image_content or not filename:
            print(f"    ✗ Не удалось скачать изображение")
            stats['errors'] += 1
            time.sleep(0.5)  # Небольшая задержка перед следующим
            continue
        
        # Загружаем на сервер
        new_media_id, new_url = upload_product_image(product_id, image_content, filename, api_url)
        
        if not new_media_id or not new_url:
            print(f"    ✗ Не удалось загрузить изображение на сервер")
            stats['errors'] += 1
            time.sleep(0.5)
            continue
        
        # Обновляем order для нового медиа (не критично если не получится)
        if media_order is not None and new_media_id:
            update_media_order(new_media_id, media_order, product_id, api_url)
        
        # Удаляем старую запись с внешним URL только после успешной загрузки
        if media_id:
            delete_success = delete_media(media_id, api_url)
            if not delete_success:
                print(f"    ⚠ Старая запись не удалена, но новое изображение загружено")
        
        stats['images_downloaded'] += 1
        print(f"    ✓ Изображение успешно обработано: {new_url}")
        
        # Задержка между изображениями
        time.sleep(0.5)
    
    stats['products_processed'] += 1
    # Задержка между товарами
    time.sleep(0.3)


def main():
    """Основная функция"""
    print("="*60)
    print("СКРИПТ СКАЧИВАНИЯ ИЗОБРАЖЕНИЙ ТОВАРОВ")
    print("="*60)
    print(f"API URL: {API_BASE_URL}")
    print(f"ТЕСТОВЫЙ РЕЖИМ: обработано будет только {TEST_LIMIT} товаров")
    print("="*60)
    
    # Авторизация
    print("\n[ШАГ 1] Авторизация...")
    if not login(API_BASE_URL):
        print("✗ Не удалось авторизоваться. Скрипт прерван.")
        return
    
    # Получаем список товаров
    print(f"\n[ШАГ 2] Получение списка товаров (лимит: {TEST_LIMIT})...")
    products = get_all_products(API_BASE_URL, limit=TEST_LIMIT)
    
    if not products:
        print("✗ Не удалось получить список товаров или товаров нет")
        return
    
    print(f"Найдено товаров для обработки: {len(products)}")
    
    # Обрабатываем каждый товар
    print(f"\n[ШАГ 3] Обработка изображений товаров...")
    print("="*60)
    
    for product in products:
        try:
            process_product_images(product, API_BASE_URL)
        except KeyboardInterrupt:
            print("\n\n⚠ Прервано пользователем")
            break
        except Exception as e:
            print(f"\n✗ Ошибка при обработке товара: {e}")
            stats['errors'] += 1
            continue
    
    # Выводим статистику
    print("\n" + "="*60)
    print("ОБРАБОТКА ЗАВЕРШЕНА")
    print("="*60)
    print(f"Обработано товаров: {stats['products_processed']}")
    print(f"Проверено изображений: {stats['images_checked']}")
    print(f"Скачано изображений: {stats['images_downloaded']}")
    print(f"Пропущено изображений (локальные): {stats['images_skipped']}")
    print(f"Ошибок: {stats['errors']}")
    print("="*60)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Скачивание внешних изображений товаров на сервер')
    parser.add_argument('--api-url', type=str, default=API_BASE_URL,
                        help=f'URL API сервера (по умолчанию: {API_BASE_URL})')
    parser.add_argument('--limit', type=int, default=TEST_LIMIT,
                        help=f'Количество товаров для обработки (по умолчанию: {TEST_LIMIT})')
    parser.add_argument('--yes', action='store_true',
                        help='Запустить без подтверждения')
    
    args = parser.parse_args()
    
    # Обновляем настройки
    globals()['API_BASE_URL'] = args.api_url
    globals()['TEST_LIMIT'] = args.limit
    
    print(f"API URL: {API_BASE_URL}")
    print(f"Лимит товаров: {TEST_LIMIT}")
    
    if args.yes:
        main()
    else:
        response = input(f"\nНачать обработку {TEST_LIMIT} товаров? (yes/no): ")
        if response.lower() in ['yes', 'y', 'да', 'д']:
            main()
        else:
            print("Обработка отменена.")

