#!/usr/bin/env python3
"""
Скрипт для миграции проблемных таблиц с правильной обработкой ссылок
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Локальная база данных
LOCAL_DB_URL = "postgresql://pospro:yfcnhjqrf@localhost:5432/pospro_server_db"

# База данных на Render
RENDER_DB_URL = os.getenv("RENDER_DATABASE_URL")

def get_connection(db_url):
    """Создает подключение к базе данных"""
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None

def table_exists(conn, table_name):
    """Проверяет существование таблицы"""
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            );
        """, (table_name,))
        return cursor.fetchone()[0]

def get_existing_ids(conn, table_name, id_column='id'):
    """Получает список существующих ID в таблице"""
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT {id_column} FROM {table_name};")
        return [row[0] for row in cursor.fetchall()]

def export_table_data(conn, table_name):
    """Экспортирует данные из таблицы"""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def clear_table(conn, table_name):
    """Очищает таблицу"""
    with conn.cursor() as cursor:
        # Экранируем зарезервированные слова
        escaped_table_name = f'"{table_name}"' if table_name.upper() in ['ORDER', 'USER', 'GROUP', 'SELECT', 'FROM', 'WHERE'] else table_name
        cursor.execute(f"TRUNCATE TABLE {escaped_table_name} RESTART IDENTITY CASCADE;")
        conn.commit()
        print(f"Таблица {table_name} очищена")

def fix_category_data(local_data, render_conn):
    """Исправляет данные категорий"""
    print("Исправление данных категорий...")
    
    # Получаем существующие ID категорий на Render
    existing_category_ids = get_existing_ids(render_conn, 'category')
    print(f"Существующие ID категорий на Render: {existing_category_ids}")
    
    fixed_data = []
    for row in local_data:
        fixed_row = dict(row)
        
        # Если parent_id не существует, устанавливаем NULL
        if 'parent_id' in fixed_row and fixed_row['parent_id'] is not None:
            if fixed_row['parent_id'] not in existing_category_ids:
                print(f"   Исправлено: category ID {fixed_row['id']} parent_id={fixed_row['parent_id']} -> NULL")
                fixed_row['parent_id'] = None
        
        fixed_data.append(fixed_row)
    
    return fixed_data

def fix_product_data(local_data, render_conn):
    """Исправляет данные продуктов"""
    print("Исправление данных продуктов...")
    
    # Получаем существующие ID категорий и брендов на Render
    existing_category_ids = get_existing_ids(render_conn, 'category')
    existing_brand_ids = get_existing_ids(render_conn, 'brand')
    existing_status_ids = get_existing_ids(render_conn, 'status')
    
    print(f"Существующие ID категорий: {existing_category_ids}")
    print(f"Существующие ID брендов: {existing_brand_ids}")
    print(f"Существующие ID статусов: {existing_status_ids}")
    
    fixed_data = []
    for row in local_data:
        fixed_row = dict(row)
        
        # Исправляем category_id
        if 'category_id' in fixed_row and fixed_row['category_id'] is not None:
            if fixed_row['category_id'] not in existing_category_ids:
                print(f"   Исправлено: product ID {fixed_row['id']} category_id={fixed_row['category_id']} -> NULL")
                fixed_row['category_id'] = None
        
        # Исправляем brand_id
        if 'brand_id' in fixed_row and fixed_row['brand_id'] is not None:
            if fixed_row['brand_id'] not in existing_brand_ids:
                print(f"   Исправлено: product ID {fixed_row['id']} brand_id={fixed_row['brand_id']} -> NULL")
                fixed_row['brand_id'] = None
        
        # Исправляем status
        if 'status' in fixed_row and fixed_row['status'] is not None:
            if fixed_row['status'] not in existing_status_ids:
                print(f"   Исправлено: product ID {fixed_row['id']} status={fixed_row['status']} -> NULL")
                fixed_row['status'] = None
        
        fixed_data.append(fixed_row)
    
    return fixed_data

def fix_product_dependent_data(local_data, render_conn, table_name):
    """Исправляет данные, зависящие от продуктов"""
    print(f"Исправление данных {table_name}...")
    
    # Получаем существующие ID продуктов на Render
    existing_product_ids = get_existing_ids(render_conn, 'product')
    print(f"Существующие ID продуктов на Render: {existing_product_ids}")
    
    fixed_data = []
    for row in local_data:
        fixed_row = dict(row)
        
        # Если product_id не существует, пропускаем запись
        if 'product_id' in fixed_row and fixed_row['product_id'] is not None:
            if fixed_row['product_id'] not in existing_product_ids:
                print(f"   Пропущено: {table_name} с product_id={fixed_row['product_id']}")
                continue
        
        fixed_data.append(fixed_row)
    
    return fixed_data

def fix_order_items_data(local_data, render_conn):
    """Исправляет данные элементов заказов"""
    print("Исправление данных элементов заказов...")
    
    # Получаем существующие ID продуктов и заказов на Render
    existing_product_ids = get_existing_ids(render_conn, 'product')
    existing_order_ids = get_existing_ids(render_conn, 'orders')
    
    print(f"Существующие ID продуктов: {existing_product_ids}")
    print(f"Существующие ID заказов: {existing_order_ids}")
    
    fixed_data = []
    for row in local_data:
        fixed_row = dict(row)
        
        # Если product_id не существует, пропускаем запись
        if 'product_id' in fixed_row and fixed_row['product_id'] is not None:
            if fixed_row['product_id'] not in existing_product_ids:
                print(f"   Пропущено: order_items с product_id={fixed_row['product_id']}")
                continue
        
        # Если order_id не существует, пропускаем запись
        if 'order_id' in fixed_row and fixed_row['order_id'] is not None:
            if fixed_row['order_id'] not in existing_order_ids:
                print(f"   Пропущено: order_items с order_id={fixed_row['order_id']}")
                continue
        
        fixed_data.append(fixed_row)
    
    return fixed_data

def fix_favorites_data(local_data, render_conn):
    """Исправляет данные избранного"""
    print("Исправление данных избранного...")
    
    # Получаем существующие ID продуктов и пользователей на Render
    existing_product_ids = get_existing_ids(render_conn, 'product')
    existing_user_ids = get_existing_ids(render_conn, 'users')
    
    print(f"Существующие ID продуктов: {existing_product_ids}")
    print(f"Существующие ID пользователей: {existing_user_ids}")
    
    fixed_data = []
    for row in local_data:
        fixed_row = dict(row)
        
        # Если product_id не существует, пропускаем запись
        if 'product_id' in fixed_row and fixed_row['product_id'] is not None:
            if fixed_row['product_id'] not in existing_product_ids:
                print(f"   Пропущено: favorites с product_id={fixed_row['product_id']}")
                continue
        
        # Если user_id не существует, пропускаем запись
        if 'user_id' in fixed_row and fixed_row['user_id'] is not None:
            if fixed_row['user_id'] not in existing_user_ids:
                print(f"   Пропущено: favorites с user_id={fixed_row['user_id']}")
                continue
        
        fixed_data.append(fixed_row)
    
    return fixed_data

def insert_table_data(conn, table_name, data):
    """Вставляет данные в таблицу"""
    if not data:
        print(f"Таблица {table_name} пустая, пропускаем")
        return
    
    with conn.cursor() as cursor:
        # Экранируем зарезервированные слова для имени таблицы
        escaped_table_name = f'"{table_name}"' if table_name.upper() in ['ORDER', 'USER', 'GROUP', 'SELECT', 'FROM', 'WHERE'] else table_name
        
        # Получаем структуру таблицы
        cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' 
            ORDER BY ordinal_position;
        """)
        columns = [row[0] for row in cursor.fetchall()]
        
        # Экранируем зарезервированные слова в именах колонок
        escaped_columns = [f'"{col}"' if col.upper() in ['ORDER', 'USER', 'GROUP', 'SELECT', 'FROM', 'WHERE'] else col for col in columns]
        
        # Создаем SQL для вставки
        placeholders = ', '.join(['%s'] * len(columns))
        insert_sql = f"INSERT INTO {escaped_table_name} ({', '.join(escaped_columns)}) VALUES ({placeholders})"
        
        # Подготавливаем данные для вставки
        values_list = []
        for row in data:
            values = []
            for col in columns:
                value = row.get(col)
                # Обрабатываем специальные типы данных
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif isinstance(value, dict):
                    value = json.dumps(value)
                values.append(value)
            values_list.append(tuple(values))
        
        # Вставляем данные
        cursor.executemany(insert_sql, values_list)
        conn.commit()
        print(f"Вставлено {len(values_list)} записей в таблицу {table_name}")

def migrate_table(local_conn, render_conn, table_name):
    """Мигрирует данные одной таблицы"""
    print(f"\nМигрируем таблицу: {table_name}")
    
    # Проверяем существование таблицы на Render
    if not table_exists(render_conn, table_name):
        print(f"Таблица {table_name} не существует на Render, пропускаем")
        return
    
    # Экспортируем данные из локальной базы
    print(f"Экспорт данных из локальной базы...")
    local_data = export_table_data(local_conn, table_name)
    print(f"   Найдено {len(local_data)} записей")
    
    if not local_data:
        print(f"Таблица {table_name} пустая, пропускаем")
        return
    
    # Исправляем данные в зависимости от таблицы
    if table_name == 'category':
        fixed_data = fix_category_data(local_data, render_conn)
    elif table_name == 'product':
        fixed_data = fix_product_data(local_data, render_conn)
    elif table_name in ['product_characteristic', 'product_document', 'product_media']:
        fixed_data = fix_product_dependent_data(local_data, render_conn, table_name)
    elif table_name == 'order_items':
        fixed_data = fix_order_items_data(local_data, render_conn)
    elif table_name == 'favorites':
        fixed_data = fix_favorites_data(local_data, render_conn)
    else:
        fixed_data = local_data
    
    if not fixed_data:
        print(f"Все записи в таблице {table_name} были пропущены из-за проблемных ссылок")
        return
    
    print(f"   Осталось {len(fixed_data)} записей после исправлений")
    
    # Очищаем таблицу на Render
    print(f"Очистка таблицы на Render...")
    clear_table(render_conn, table_name)
    
    # Импортируем данные в базу на Render
    print(f"Импорт данных в базу на Render...")
    insert_table_data(render_conn, table_name, fixed_data)

def main():
    """Основная функция миграции"""
    print("Миграция проблемных таблиц с правильной обработкой ссылок")
    print("=" * 60)
    
    # Проверяем URL базы данных на Render
    if not RENDER_DB_URL:
        print("Ошибка: Не установлена переменная RENDER_DATABASE_URL")
        return
    
    # Подключаемся к локальной базе
    print("Подключение к локальной базе данных...")
    local_conn = get_connection(LOCAL_DB_URL)
    if not local_conn:
        return
    
    # Подключаемся к базе на Render
    print("Подключение к базе данных на Render...")
    render_conn = get_connection(RENDER_DB_URL)
    if not render_conn:
        local_conn.close()
        return
    
    # Список проблемных таблиц для миграции
    problematic_tables = [
        'category',
        'product', 
        'product_characteristic',
        'product_document',
        'product_media',
        'order_items',
        'favorites'
    ]
    
    try:
        print(f"\nТаблицы для миграции: {', '.join(problematic_tables)}")
        print(f"Начинаем миграцию...")
        
        # Мигрируем каждую проблемную таблицу
        for table_name in problematic_tables:
            try:
                migrate_table(local_conn, render_conn, table_name)
            except Exception as e:
                print(f"Ошибка при миграции таблицы {table_name}: {e}")
                # Откатываем транзакцию для этой таблицы
                try:
                    render_conn.rollback()
                except:
                    pass
                continue
        
        print("\n" + "=" * 60)
        print("Миграция проблемных таблиц завершена!")
        print("Проверьте данные в базе на Render")
        
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        local_conn.close()
        render_conn.close()
        print("Соединения закрыты")

if __name__ == "__main__":
    main()
