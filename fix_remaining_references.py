#!/usr/bin/env python3
"""
Скрипт для исправления оставшихся проблемных ссылок
"""

import os
import sys
import psycopg2
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

def fix_remaining_references(conn):
    """Исправляет оставшиеся проблемные ссылки"""
    with conn.cursor() as cursor:
        print("Исправление оставшихся проблемных ссылок...")
        
        # Исправляем ссылки на несуществующие категории
        print("1. Исправление ссылок на несуществующие категории...")
        cursor.execute("UPDATE category SET parent_id = NULL WHERE parent_id = 125;")
        affected = cursor.rowcount
        print(f"   Обновлено {affected} записей в category (parent_id=125 -> NULL)")
        
        cursor.execute("UPDATE product SET category_id = NULL WHERE category_id = 125;")
        affected = cursor.rowcount
        print(f"   Обновлено {affected} записей в product (category_id=125 -> NULL)")
        
        # Исправляем ссылки на несуществующие продукты
        print("2. Исправление ссылок на несуществующие продукты...")
        cursor.execute("DELETE FROM product_characteristic WHERE product_id = 31;")
        affected = cursor.rowcount
        print(f"   Удалено {affected} записей в product_characteristic (product_id=31)")
        
        cursor.execute("DELETE FROM product_media WHERE product_id = 31;")
        affected = cursor.rowcount
        print(f"   Удалено {affected} записей в product_media (product_id=31)")
        
        cursor.execute("DELETE FROM order_items WHERE product_id = 23;")
        affected = cursor.rowcount
        print(f"   Удалено {affected} записей в order_items (product_id=23)")
        
        cursor.execute("DELETE FROM favorites WHERE product_id = 116;")
        affected = cursor.rowcount
        print(f"   Удалено {affected} записей в favorites (product_id=116)")
        
        # Коммитим изменения
        conn.commit()
        print("Все изменения сохранены")

def main():
    """Основная функция"""
    print("Исправление оставшихся проблемных ссылок в базе на Render")
    print("=" * 60)
    
    # Проверяем URL базы данных на Render
    if not RENDER_DB_URL:
        print("Ошибка: Не установлена переменная RENDER_DATABASE_URL")
        return
    
    # Подключаемся к базе на Render
    print("Подключение к базе данных на Render...")
    conn = get_connection(RENDER_DB_URL)
    if not conn:
        return
    
    try:
        fix_remaining_references(conn)
        print("\n" + "=" * 60)
        print("Исправление завершено успешно!")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()
        print("Соединение закрыто")

if __name__ == "__main__":
    main()
