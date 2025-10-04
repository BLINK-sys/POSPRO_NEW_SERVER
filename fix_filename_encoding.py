#!/usr/bin/env python3
"""
Скрипт для исправления кодировки имен файлов в базе данных
"""
import os
import psycopg2
from urllib.parse import urlparse

def fix_filename_encoding():
    """Исправляем кодировку имен файлов в базе данных"""
    
    # Парсим URL базы данных
    db_url = "postgresql://pospro_user:FkfSdSLXtK9ZFei3tch3KmUYuLOeq1rO@dpg-d3fnijili9vc73e7pvq0-a/pospro_db"
    parsed = urlparse(db_url)
    
    # Подключаемся к базе данных
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path[1:],  # убираем первый /
        user=parsed.username,
        password=parsed.password,
        client_encoding='utf8'
    )
    
    try:
        cursor = conn.cursor()
        
        # Получаем все записи с искаженными именами файлов
        cursor.execute("SELECT id, filename FROM product_document WHERE filename ~ '[^\\x00-\\x7F]'")
        records = cursor.fetchall()
        
        print(f"Найдено записей с не-ASCII символами: {len(records)}")
        
        for record_id, filename in records:
            print(f"ID: {record_id}, Filename: {repr(filename)}")
            
            # Пытаемся исправить кодировку
            try:
                # Если файл содержит искаженные символы, попробуем разные кодировки
                fixed_filename = None
                
                # Попробуем cp1251 (Windows-1251)
                try:
                    fixed_filename = filename.encode('cp1251').decode('utf-8')
                    print(f"  Исправлено через cp1251: {fixed_filename}")
                except:
                    pass
                
                # Попробуем latin1
                if not fixed_filename:
                    try:
                        fixed_filename = filename.encode('latin1').decode('utf-8')
                        print(f"  Исправлено через latin1: {fixed_filename}")
                    except:
                        pass
                
                # Если удалось исправить, обновляем запись
                if fixed_filename and fixed_filename != filename:
                    cursor.execute(
                        "UPDATE product_document SET filename = %s WHERE id = %s",
                        (fixed_filename, record_id)
                    )
                    print(f"  Обновлено: {filename} -> {fixed_filename}")
                else:
                    print(f"  Не удалось исправить: {filename}")
                    
            except Exception as e:
                print(f"  Ошибка при исправлении: {e}")
        
        # Сохраняем изменения
        conn.commit()
        print("Изменения сохранены в базе данных")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_filename_encoding()
