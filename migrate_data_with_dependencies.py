#!/usr/bin/env python3
"""
Скрипт для миграции данных с учетом зависимостей между таблицами
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

# Порядок миграции таблиц (сначала родительские, потом дочерние)
MIGRATION_ORDER = [
    # Базовые справочники (без зависимостей)
    'product_availability_statuses',
    'status', 
    'system_brands',
    'system_users',
    'users',
    'brand',
    'order_statuses',
    
    # Категории (сначала родительские)
    'category',  # Сначала все категории
    
    # Продукты (зависят от категорий, брендов, статусов)
    'product',
    
    # Зависимые от продуктов
    'product_characteristic',
    'product_document', 
    'product_media',
    
    # Заказы (зависят от пользователей)
    'orders',
    
    # Зависимые от заказов
    'order_items',
    'order_managers',
    
    # Избранное (зависит от пользователей и продуктов)
    'favorites',
    
    # Домашняя страница
    'homepage_blocks',
    'homepage_block_items',
    'homepage_categories',
    
    # Баннеры и настройки
    'banners',
    'small_banners',
    'footer_settings',
    'benefits',
    
    # Корзина (может быть пустой)
    'cart',
]

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
    
    # Очищаем таблицу на Render
    print(f"Очистка таблицы на Render...")
    clear_table(render_conn, table_name)
    
    # Импортируем данные в базу на Render
    print(f"Импорт данных в базу на Render...")
    insert_table_data(render_conn, table_name, local_data)

def get_all_tables(local_conn):
    """Получает список всех таблиц в базе данных"""
    with local_conn.cursor() as cursor:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        return [row[0] for row in cursor.fetchall()]

def main():
    """Основная функция миграции"""
    print("Начинаем миграцию данных из локальной БД в Render")
    print("=" * 60)
    
    # Проверяем URL базы данных на Render
    if not RENDER_DB_URL:
        print("Ошибка: Не установлена переменная RENDER_DATABASE_URL")
        print("   Добавьте в .env файл: RENDER_DATABASE_URL=postgresql://...")
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
    
    try:
        # Получаем список всех таблиц
        print("\nПолучение списка таблиц...")
        all_tables = get_all_tables(local_conn)
        print(f"   Найдено {len(all_tables)} таблиц: {', '.join(all_tables)}")
        
        # Фильтруем таблицы, которые есть в порядке миграции
        tables_to_migrate = [table for table in MIGRATION_ORDER if table in all_tables]
        
        # Добавляем таблицы, которых нет в порядке миграции
        remaining_tables = [table for table in all_tables if table not in MIGRATION_ORDER]
        tables_to_migrate.extend(remaining_tables)
        
        print(f"\nПорядок миграции:")
        for i, table in enumerate(tables_to_migrate, 1):
            print(f"   {i}. {table}")
        
        # Подтверждение от пользователя
        print(f"\nВНИМАНИЕ: Все данные в базе на Render будут заменены!")
        response = input("Продолжить? (yes/no): ")
        if response.lower() != 'yes':
            print("Миграция отменена")
            return
        
        # Мигрируем каждую таблицу в правильном порядке
        for table_name in tables_to_migrate:
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
        print("Миграция завершена успешно!")
        print("Проверьте данные в базе на Render")
        
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        local_conn.close()
        render_conn.close()
        print("Соединения закрыты")

if __name__ == "__main__":
    main()
