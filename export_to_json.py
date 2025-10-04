#!/usr/bin/env python3
"""
Скрипт для экспорта данных из локальной PostgreSQL базы в JSON файлы
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

def get_connection(db_url):
    """Создает подключение к базе данных"""
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None

def get_table_names(conn):
    """Получает список всех таблиц в базе данных"""
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        return [row[0] for row in cursor.fetchall()]

def export_table_to_json(conn, table_name):
    """Экспортирует данные из таблицы в JSON"""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        
        # Конвертируем в список словарей
        data = []
        for row in rows:
            row_dict = {}
            for key, value in row.items():
                if isinstance(value, datetime):
                    row_dict[key] = value.isoformat()
                elif isinstance(value, dict):
                    row_dict[key] = value
                else:
                    row_dict[key] = value
            data.append(row_dict)
        
        return data

def save_json_file(data, filename):
    """Сохраняет данные в JSON файл"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    """Основная функция экспорта"""
    print("🚀 Экспорт данных из локальной БД в JSON файлы")
    print("=" * 60)
    
    # Создаем папку для экспорта
    export_dir = "exported_data"
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)
        print(f"📁 Создана папка: {export_dir}")
    
    # Подключаемся к локальной базе
    print("🔗 Подключение к локальной базе данных...")
    conn = get_connection(LOCAL_DB_URL)
    if not conn:
        return
    
    try:
        # Получаем список таблиц
        print("\n📋 Получение списка таблиц...")
        tables = get_table_names(conn)
        print(f"   Найдено {len(tables)} таблиц: {', '.join(tables)}")
        
        # Экспортируем каждую таблицу
        exported_tables = []
        for table_name in tables:
            print(f"\n📤 Экспорт таблицы: {table_name}")
            try:
                data = export_table_to_json(conn, table_name)
                filename = os.path.join(export_dir, f"{table_name}.json")
                save_json_file(data, filename)
                print(f"   ✓ Экспортировано {len(data)} записей в {filename}")
                exported_tables.append({
                    'table': table_name,
                    'filename': filename,
                    'records': len(data)
                })
            except Exception as e:
                print(f"   ❌ Ошибка при экспорте таблицы {table_name}: {e}")
                continue
        
        # Создаем индексный файл
        index_file = os.path.join(export_dir, "export_index.json")
        index_data = {
            'export_date': datetime.now().isoformat(),
            'tables': exported_tables,
            'total_tables': len(exported_tables),
            'total_records': sum(t['records'] for t in exported_tables)
        }
        save_json_file(index_data, index_file)
        
        print("\n" + "=" * 60)
        print("✅ Экспорт завершен успешно!")
        print(f"📁 Данные сохранены в папке: {export_dir}")
        print(f"📊 Экспортировано {len(exported_tables)} таблиц")
        print(f"📄 Всего записей: {sum(t['records'] for t in exported_tables)}")
        print(f"📋 Индекс сохранен в: {index_file}")
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        conn.close()
        print("🔌 Соединение закрыто")

if __name__ == "__main__":
    main()
