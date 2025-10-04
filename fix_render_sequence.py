#!/usr/bin/env python3
"""
Скрипт для исправления последовательности ID в таблице product_media на Render
"""
import os
import psycopg2

def fix_render_sequence():
    """Исправляет последовательность ID в таблице product_media на Render"""
    
    # Получаем URL базы данных Render
    db_url = os.getenv("RENDER_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not found in environment variables")
        return
    
    print(f"Database URL: {db_url}")
    
    try:
        # Подключаемся к базе данных
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("\n=== Checking product_media table ===")
        
        # Получаем максимальный ID
        cursor.execute("SELECT MAX(id) FROM product_media")
        max_id = cursor.fetchone()[0]
        print(f"Max ID in table: {max_id}")
        
        # Получаем количество записей
        cursor.execute("SELECT COUNT(*) FROM product_media")
        count = cursor.fetchone()[0]
        print(f"Record count: {count}")
        
        # Проверяем текущее значение последовательности
        cursor.execute("SELECT last_value FROM product_media_id_seq")
        last_value = cursor.fetchone()[0]
        print(f"Current sequence value: {last_value}")
        
        # Проверяем nextval
        cursor.execute("SELECT nextval('product_media_id_seq')")
        next_val = cursor.fetchone()[0]
        print(f"Next sequence value: {next_val}")
        
        # Если последовательность отстает от максимального ID
        if max_id and last_value < max_id:
            print(f"\nWARNING: Sequence is behind! Max ID: {max_id}, sequence: {last_value}")
            
            # Исправляем последовательность
            new_value = max_id + 1
            cursor.execute(f"SELECT setval('product_media_id_seq', {new_value})")
            conn.commit()
            
            print(f"SUCCESS: Sequence updated to {new_value}")
            
            # Проверяем новое значение
            cursor.execute("SELECT last_value FROM product_media_id_seq")
            new_last_value = cursor.fetchone()[0]
            print(f"New sequence value: {new_last_value}")
            
        else:
            print("SUCCESS: Sequence is OK")
        
        # Показываем последние записи
        print(f"\n=== Last 5 records ===")
        cursor.execute("SELECT id, product_id, url, media_type FROM product_media ORDER BY id DESC LIMIT 5")
        records = cursor.fetchall()
        for record in records:
            print(f"ID: {record[0]}, Product: {record[1]}, URL: {record[2][:50]}..., Type: {record[3]}")
        
        cursor.close()
        conn.close()
        
        print("\nSUCCESS: Check completed")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fix_render_sequence()
