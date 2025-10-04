#!/usr/bin/env python3
"""
Скрипт для импорта данных из JSON файлов в базу данных на Render
"""

import os
import sys
import psycopg2
import json
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

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

def load_json_file(filename):
    """Загружает данные из JSON файла"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки файла {filename}: {e}")
        return None

def clear_table(conn, table_name):
    """Очищает таблицу"""
    with conn.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;")
        conn.commit()
        print(f"✓ Таблица {table_name} очищена")

def insert_table_data(conn, table_name, data):
    """Вставляет данные в таблицу"""
    if not data:
        print(f"⚠ Таблица {table_name} пустая, пропускаем")
        return
    
    with conn.cursor() as cursor:
        # Получаем структуру таблицы
        cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' 
            ORDER BY ordinal_position;
        """)
        columns = [row[0] for row in cursor.fetchall()]
        
        # Создаем SQL для вставки
        placeholders = ', '.join(['%s'] * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        
        # Подготавливаем данные для вставки
        values_list = []
        for row in data:
            values = []
            for col in columns:
                value = row.get(col)
                # Обрабатываем специальные типы данных
                if isinstance(value, str) and value.endswith('Z'):
                    # Пытаемся распарсить ISO дату
                    try:
                        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except:
                        pass
                values.append(value)
            values_list.append(tuple(values))
        
        # Вставляем данные
        cursor.executemany(insert_sql, values_list)
        conn.commit()
        print(f"✓ Вставлено {len(values_list)} записей в таблицу {table_name}")

def import_table(conn, table_name, json_file):
    """Импортирует данные одной таблицы"""
    print(f"\n🔄 Импорт таблицы: {table_name}")
    
    # Загружаем данные из JSON
    print(f"📤 Загрузка данных из {json_file}...")
    data = load_json_file(json_file)
    if data is None:
        return
    
    print(f"   Найдено {len(data)} записей")
    
    if not data:
        print(f"⚠ Таблица {table_name} пустая, пропускаем")
        return
    
    # Очищаем таблицу на Render
    print(f"🗑️ Очистка таблицы на Render...")
    clear_table(conn, table_name)
    
    # Импортируем данные в базу на Render
    print(f"📥 Импорт данных в базу на Render...")
    insert_table_data(conn, table_name, data)

def main():
    """Основная функция импорта"""
    print("🚀 Импорт данных из JSON файлов в Render")
    print("=" * 60)
    
    # Проверяем URL базы данных на Render
    if not RENDER_DB_URL:
        print("❌ Ошибка: Не установлена переменная RENDER_DATABASE_URL")
        print("   Добавьте в .env файл: RENDER_DATABASE_URL=postgresql://...")
        return
    
    # Проверяем папку с экспортированными данными
    export_dir = "exported_data"
    if not os.path.exists(export_dir):
        print(f"❌ Папка {export_dir} не найдена")
        print("   Сначала запустите export_to_json.py")
        return
    
    # Загружаем индекс
    index_file = os.path.join(export_dir, "export_index.json")
    if not os.path.exists(index_file):
        print(f"❌ Файл индекса {index_file} не найден")
        return
    
    index_data = load_json_file(index_file)
    if not index_data:
        return
    
    print(f"📋 Индекс загружен:")
    print(f"   Дата экспорта: {index_data.get('export_date', 'неизвестно')}")
    print(f"   Таблиц: {index_data.get('total_tables', 0)}")
    print(f"   Записей: {index_data.get('total_records', 0)}")
    
    # Подключаемся к базе на Render
    print("\n🔗 Подключение к базе данных на Render...")
    conn = get_connection(RENDER_DB_URL)
    if not conn:
        return
    
    try:
        # Подтверждение от пользователя
        print(f"\n⚠️  ВНИМАНИЕ: Все данные в базе на Render будут заменены!")
        response = input("Продолжить? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Импорт отменен")
            return
        
        # Импортируем каждую таблицу
        tables = index_data.get('tables', [])
        for table_info in tables:
            table_name = table_info['table']
            json_file = table_info['filename']
            
            if os.path.exists(json_file):
                try:
                    import_table(conn, table_name, json_file)
                except Exception as e:
                    print(f"❌ Ошибка при импорте таблицы {table_name}: {e}")
                    continue
            else:
                print(f"❌ Файл {json_file} не найден")
        
        print("\n" + "=" * 60)
        print("✅ Импорт завершен успешно!")
        print("🔍 Проверьте данные в базе на Render")
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        conn.close()
        print("🔌 Соединение закрыто")

if __name__ == "__main__":
    main()
