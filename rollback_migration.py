"""
Скрипт для отката миграции данных - удаление всех записей, созданных во время миграции.

Порядок выполнения (в обратном порядке):
1. Удаление товаров
2. Удаление категорий
3. Удаление брендов

Скрипт читает ту же базу products.db, что использовалась для миграции,
и находит соответствующие записи на сервере для удаления.
"""

import sqlite3
import requests
import time
import os
import sys
from urllib.parse import quote
import unicodedata
import re
import argparse

# Настройки API
API_BASE_URL = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
OLD_DB_PATH = os.path.join(os.path.dirname(__file__), 'products.db')

# Словари для хранения найденных ID для удаления
products_to_delete = []  # [product_id]
categories_to_delete = []  # [category_id]
brands_to_delete = []  # [brand_id]

# Кеши для поиска существующих записей
brands_cache = {}  # {(name, country): brand_id}
categories_cache = {}  # {(name, parent_id): category_id}
products_cache = {}  # {article: product_id}
products_by_name_brand = {}  # {(name, brand): product_id}


def normalize_url(api_url, endpoint):
    """
    Нормализует URL, убирая /api из пути для эндпоинтов, которые не имеют префикса /api
    """
    base_url = api_url.replace('/api', '') if '/api' in api_url else api_url
    base_url = base_url.rstrip('/')
    endpoint = endpoint.lstrip('/')
    return f"{base_url}/{endpoint}"


def check_db_structure(conn):
    """Проверяет структуру базы данных и возвращает список таблиц и их колонок"""
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"Найдено таблиц: {len(tables)}")
    print(f"Таблицы: {', '.join(tables)}")
    
    structure = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]
        structure[table] = columns
    
    return structure


def load_all_brands(api_url):
    """Загружает все существующие бренды в кеш"""
    global brands_cache
    
    brands_url = normalize_url(api_url, 'meta/brands')
    print(f"  Загрузка брендов с {brands_url}...")
    try:
        response = requests.get(brands_url, timeout=60)
        if response.status_code == 200:
            existing_brands = response.json()
            for brand in existing_brands:
                name = brand.get('name', '').strip()
                country = brand.get('country', '').strip() if brand.get('country') else ''
                brand_id = brand.get('id')
                if name and brand_id:
                    cache_key = (name, country)
                    brands_cache[cache_key] = brand_id
            print(f"  ✓ Загружено {len(brands_cache)} брендов")
        else:
            print(f"  ⚠ Ошибка загрузки брендов: {response.status_code}")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке брендов: {e}")


def load_all_categories(api_url):
    """Загружает все существующие категории в кеш"""
    global categories_cache
    
    categories_url = normalize_url(api_url, 'categories/')
    print(f"  Загрузка категорий с {categories_url}...")
    try:
        response = requests.get(categories_url, timeout=60)
        if response.status_code == 200:
            existing_categories = response.json()
            for category in existing_categories:
                name = category.get('name', '').strip()
                parent_id = category.get('parent_id')
                category_id = category.get('id')
                if name and category_id:
                    cache_key = (name, parent_id)
                    categories_cache[cache_key] = category_id
            print(f"  ✓ Загружено {len(categories_cache)} категорий")
        else:
            print(f"  ⚠ Ошибка загрузки категорий: {response.status_code}")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке категорий: {e}")


def load_all_products(api_url):
    """Загружает все существующие товары в кеш"""
    global products_cache, products_by_name_brand
    
    products_url = normalize_url(api_url, 'products/')
    print(f"  Загрузка товаров с {products_url}...")
    try:
        response = requests.get(products_url, timeout=60)
        if response.status_code == 200:
            existing_products = response.json()
            for product in existing_products:
                article = product.get('article', '')
                name = product.get('name', '')
                brand = product.get('brand', '') or ''
                product_id = product.get('id')
                
                if article and product_id:
                    products_cache[article] = product_id
                
                if name and product_id:
                    cache_key = (name.strip(), brand.strip())
                    products_by_name_brand[cache_key] = product_id
            
            print(f"  ✓ Загружено {len(existing_products)} товаров")
            print(f"    - По артикулу: {len(products_cache)}")
            print(f"    - По имени+бренду: {len(products_by_name_brand)}")
        else:
            print(f"  ⚠ Ошибка загрузки товаров: {response.status_code}")
    except Exception as e:
        print(f"  ✗ Ошибка при загрузке товаров: {e}")


def find_products_to_delete(conn, structure, api_url):
    """Находит товары для удаления на основе данных из products.db"""
    global products_to_delete
    
    products_table = None
    for table in structure.keys():
        if 'product' in table.lower():
            products_table = table
            break
    
    if not products_table:
        print("  ⚠ Таблица товаров не найдена в базе данных")
        return
    
    products_columns = structure[products_table]
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {products_table}")
    products = cursor.fetchall()
    
    print(f"\n  Поиск товаров для удаления (всего в БД: {len(products)})...")
    
    for product_row in products:
        product_dict = dict(zip(products_columns, product_row))
        
        name = product_dict.get('name', '').strip() or product_dict.get('title', '').strip() or product_dict.get('fullName', '').strip()
        article = product_dict.get('article', '').strip() or product_dict.get('code', '').strip() or product_dict.get('sku', '').strip()
        brand_name = product_dict.get('brand', '').strip() or product_dict.get('brand_name', '').strip()
        
        product_id = None
        
        # Ищем по артикулу
        if article and article in products_cache:
            product_id = products_cache[article]
        
        # Если не нашли по артикулу, ищем по имени+бренду
        if not product_id and name:
            cache_key = (name, brand_name)
            if cache_key in products_by_name_brand:
                product_id = products_by_name_brand[cache_key]
        
        # Также проверяем артикулы с префиксом MIGR- (созданные при миграции)
        if not product_id:
            for cached_article, cached_id in products_cache.items():
                if cached_article.startswith('MIGR-'):
                    # Проверяем, соответствует ли этот товар текущему по имени
                    if name and cached_article:
                        # Можно дополнительно проверить по имени, но для безопасности
                        # удаляем только если точно знаем соответствие
                        pass
        
        if product_id:
            if product_id not in products_to_delete:
                products_to_delete.append(product_id)
                print(f"    ✓ Найден товар для удаления: {name} (ID: {product_id}, артикул: {article})")
        else:
            print(f"    ⚠ Товар не найден на сервере: {name} (артикул: {article})")


def find_categories_to_delete(conn, structure, api_url):
    """Находит категории для удаления на основе данных из products.db"""
    global categories_to_delete
    
    categories_table = None
    for table in structure.keys():
        if 'categor' in table.lower():
            categories_table = table
            break
    
    if not categories_table:
        print("  ⚠ Таблица категорий не найдена в базе данных")
        # Попробуем найти категории в таблице товаров
        products_table = None
        for table in structure.keys():
            if 'product' in table.lower():
                products_table = table
                break
        
        if products_table:
            products_columns = structure[products_table]
            if 'category' in products_columns or 'category_name' in products_columns:
                category_col = 'category' if 'category' in products_columns else 'category_name'
                cursor = conn.cursor()
                cursor.execute(f"SELECT DISTINCT {category_col} FROM {products_table} WHERE {category_col} IS NOT NULL AND {category_col} != ''")
                category_rows = cursor.fetchall()
                
                print(f"\n  Поиск категорий для удаления (найдено в товарах: {len(category_rows)})...")
                
                for (category_name,) in category_rows:
                    if category_name:
                        name = str(category_name).strip()
                        # Ищем категорию по имени (без учета parent_id, так как может быть разная структура)
                        found = False
                        for (cached_name, cached_parent), cached_id in categories_cache.items():
                            if cached_name == name:
                                if cached_id not in categories_to_delete:
                                    categories_to_delete.append(cached_id)
                                    print(f"    ✓ Найдена категория для удаления: {name} (ID: {cached_id})")
                                found = True
                                break
                        if not found:
                            print(f"    ⚠ Категория не найдена на сервере: {name}")
        return
    
    categories_columns = structure[categories_table]
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {categories_table} ORDER BY id")
    categories = cursor.fetchall()
    
    print(f"\n  Поиск категорий для удаления (всего в БД: {len(categories)})...")
    
    for category_row in categories:
        category_dict = dict(zip(categories_columns, category_row))
        name = category_dict.get('name', '').strip() or category_dict.get('title', '').strip()
        parent_id = category_dict.get('parent_id')
        
        if name:
            # Сначала ищем точное совпадение по (name, parent_id)
            cache_key = (name, parent_id)
            if cache_key in categories_cache:
                category_id = categories_cache[cache_key]
                if category_id not in categories_to_delete:
                    categories_to_delete.append(category_id)
                    print(f"    ✓ Найдена категория для удаления: {name} (ID: {category_id})")
            else:
                # Пробуем найти по имени без учета parent_id
                found = False
                for (cached_name, cached_parent), cached_id in categories_cache.items():
                    if cached_name == name:
                        if cached_id not in categories_to_delete:
                            categories_to_delete.append(cached_id)
                            print(f"    ✓ Найдена категория для удаления (по имени): {name} (ID: {cached_id})")
                        found = True
                        break
                if not found:
                    print(f"    ⚠ Категория не найдена на сервере: {name}")


def find_brands_to_delete(conn, structure, api_url):
    """Находит бренды для удаления на основе данных из products.db"""
    global brands_to_delete
    
    brands_table = None
    for table in structure.keys():
        if 'brand' in table.lower():
            brands_table = table
            break
    
    if not brands_table:
        print("  ⚠ Таблица брендов не найдена в базе данных")
        # Попробуем найти бренды в таблице товаров
        products_table = None
        for table in structure.keys():
            if 'product' in table.lower():
                products_table = table
                break
        
        if products_table:
            products_columns = structure[products_table]
            if 'brand' in products_columns or 'brand_name' in products_columns:
                brand_col = 'brand' if 'brand' in products_columns else 'brand_name'
                cursor = conn.cursor()
                cursor.execute(f"SELECT DISTINCT {brand_col}, country FROM {products_table} WHERE {brand_col} IS NOT NULL AND {brand_col} != ''")
                brand_rows = cursor.fetchall()
                
                print(f"\n  Поиск брендов для удаления (найдено в товарах: {len(brand_rows)})...")
                
                for brand_name, country in brand_rows:
                    if brand_name:
                        cache_key = (str(brand_name).strip(), str(country).strip() if country else '')
                        if cache_key in brands_cache:
                            brand_id = brands_cache[cache_key]
                            if brand_id not in brands_to_delete:
                                brands_to_delete.append(brand_id)
                                print(f"    ✓ Найден бренд для удаления: {brand_name} (ID: {brand_id})")
        return
    
    brands_columns = structure[brands_table]
    cursor = conn.cursor()
    cursor.execute(f"SELECT DISTINCT * FROM {brands_table}")
    brands = cursor.fetchall()
    
    print(f"\n  Поиск брендов для удаления (всего в БД: {len(brands)})...")
    
    for brand_row in brands:
        brand_dict = dict(zip(brands_columns, brand_row))
        name = brand_dict.get('name', '').strip() or brand_dict.get('title', '').strip()
        country = brand_dict.get('country', '').strip() if brand_dict.get('country') else ''
        
        if name:
            cache_key = (name, country)
            if cache_key in brands_cache:
                brand_id = brands_cache[cache_key]
                if brand_id not in brands_to_delete:
                    brands_to_delete.append(brand_id)
                    print(f"    ✓ Найден бренд для удаления: {name} (ID: {brand_id})")
            else:
                # Пробуем найти по имени без учета страны
                for (cached_name, cached_country), cached_id in brands_cache.items():
                    if cached_name == name:
                        if cached_id not in brands_to_delete:
                            brands_to_delete.append(cached_id)
                            print(f"    ✓ Найден бренд для удаления (по имени): {name} (ID: {cached_id})")
                        break


def delete_product(product_id, api_url):
    """Удаляет товар через API"""
    try:
        products_url = normalize_url(api_url, f'products/{product_id}')
        response = requests.delete(products_url, timeout=60)
        
        if response.status_code == 200:
            return True
        else:
            print(f"    ✗ Ошибка удаления товара ID {product_id}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"    ✗ Ошибка при удалении товара ID {product_id}: {e}")
        return False


def delete_category(category_id, api_url):
    """Удаляет категорию через API"""
    try:
        categories_url = normalize_url(api_url, f'categories/{category_id}')
        print(f"    Попытка удаления категории ID {category_id} через {categories_url}")
        response = requests.delete(categories_url, timeout=60)
        
        if response.status_code == 200:
            print(f"    ✓ Категория ID {category_id} успешно удалена")
            return True
        else:
            error_text = response.text[:500] if response.text else "Нет текста ошибки"
            print(f"    ✗ Ошибка удаления категории ID {category_id}: {response.status_code}")
            print(f"       Ответ сервера: {error_text}")
            return False
    except Exception as e:
        print(f"    ✗ Ошибка при удалении категории ID {category_id}: {e}")
        return False


def delete_brand(brand_id, api_url):
    """Удаляет бренд через API"""
    try:
        brands_url = normalize_url(api_url, f'meta/brands/{brand_id}')
        response = requests.delete(brands_url, timeout=60)
        
        if response.status_code == 200:
            return True
        else:
            print(f"    ✗ Ошибка удаления бренда ID {brand_id}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"    ✗ Ошибка при удалении бренда ID {brand_id}: {e}")
        return False


def rollback_migration(api_base_url=None, db_path=None):
    """
    Основная функция отката миграции
    
    Args:
        api_base_url: URL API сервера
        db_path: Путь к файлу products.db
    """
    api_url = api_base_url or API_BASE_URL
    db_path_local = db_path or OLD_DB_PATH
    
    if not os.path.exists(db_path_local):
        print(f"✗ Файл базы данных не найден: {db_path_local}")
        return
    
    print(f"Подключение к базе данных: {db_path_local}")
    conn = sqlite3.connect(db_path_local)
    
    # Проверяем структуру базы
    print("\n" + "="*60)
    print("ПРОВЕРКА СТРУКТУРЫ БАЗЫ ДАННЫХ")
    print("="*60)
    structure = check_db_structure(conn)
    
    # Загружаем все существующие записи с сервера
    print("\n" + "="*60)
    print("ЗАГРУЗКА СУЩЕСТВУЮЩИХ ЗАПИСЕЙ С СЕРВЕРА")
    print("="*60)
    load_all_products(api_url)
    load_all_categories(api_url)
    load_all_brands(api_url)
    
    # Находим записи для удаления
    print("\n" + "="*60)
    print("ПОИСК ЗАПИСЕЙ ДЛЯ УДАЛЕНИЯ")
    print("="*60)
    find_products_to_delete(conn, structure, api_url)
    find_categories_to_delete(conn, structure, api_url)
    find_brands_to_delete(conn, structure, api_url)
    
    conn.close()
    
    # Удаляем в обратном порядке
    print("\n" + "="*60)
    print("УДАЛЕНИЕ ЗАПИСЕЙ")
    print("="*60)
    
    # ШАГ 1: Удаление товаров
    print(f"\n[ШАГ 1] Удаление товаров (найдено: {len(products_to_delete)})...")
    deleted_products = 0
    for product_id in products_to_delete:
        if delete_product(product_id, api_url):
            deleted_products += 1
        time.sleep(0.3)  # Задержка между запросами
    
    print(f"  ✓ Удалено товаров: {deleted_products}/{len(products_to_delete)}")
    
    # ШАГ 2: Удаление категорий
    print(f"\n[ШАГ 2] Удаление категорий (найдено: {len(categories_to_delete)})...")
    deleted_categories = 0
    for category_id in categories_to_delete:
        if delete_category(category_id, api_url):
            deleted_categories += 1
        time.sleep(0.2)
    
    print(f"  ✓ Удалено категорий: {deleted_categories}/{len(categories_to_delete)}")
    
    # ШАГ 3: Удаление брендов
    print(f"\n[ШАГ 3] Удаление брендов (найдено: {len(brands_to_delete)})...")
    deleted_brands = 0
    for brand_id in brands_to_delete:
        if delete_brand(brand_id, api_url):
            deleted_brands += 1
        time.sleep(0.2)
    
    print(f"  ✓ Удалено брендов: {deleted_brands}/{len(brands_to_delete)}")
    
    print("\n" + "="*60)
    print("ОТКАТ МИГРАЦИИ ЗАВЕРШЕН")
    print("="*60)
    print(f"Удалено товаров: {deleted_products}")
    print(f"Удалено категорий: {deleted_categories}")
    print(f"Удалено брендов: {deleted_brands}")


if __name__ == '__main__':
    print("="*60)
    print("СКРИПТ ОТКАТА МИГРАЦИИ ДАННЫХ")
    print("="*60)
    
    default_api_url = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
    default_db_path = os.path.join(os.path.dirname(__file__), 'products.db')
    
    parser = argparse.ArgumentParser(description='Откат миграции данных - удаление записей в обратном порядке')
    parser.add_argument('--api-url', type=str, default=default_api_url,
                        help=f'URL API сервера (по умолчанию: {default_api_url})')
    parser.add_argument('--db-path', type=str, default=default_db_path,
                        help=f'Путь к файлу products.db (по умолчанию: {default_db_path})')
    parser.add_argument('--yes', action='store_true',
                        help='Запустить откат без подтверждения')
    
    args = parser.parse_args()
    
    globals()['API_BASE_URL'] = args.api_url
    globals()['OLD_DB_PATH'] = args.db_path
    
    print(f"API URL: {API_BASE_URL}")
    print(f"База данных: {OLD_DB_PATH}")
    print("\n⚠ ВНИМАНИЕ: Это действие удалит все записи, соответствующие данным из products.db!")
    print("   Порядок удаления: товары → категории → бренды")
    
    if args.yes:
        rollback_migration(API_BASE_URL, OLD_DB_PATH)
    else:
        response = input("\nПродолжить откат миграции? (yes/no): ")
        if response.lower() in ['yes', 'y', 'да', 'д']:
            rollback_migration(API_BASE_URL, OLD_DB_PATH)
        else:
            print("Откат миграции отменен.")

