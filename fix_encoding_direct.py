#!/usr/bin/env python3
"""
Прямое исправление кодировки через SQL
"""
import subprocess
import os

def fix_encoding_direct():
    """Исправляем кодировку напрямую через SQL"""
    
    # SQL команды для исправления
    sql_commands = [
        "-- Удаляем записи с проблемной кодировкой",
        "DELETE FROM product_document WHERE filename ~ '[^\\x00-\\x7F]';",
        "-- Проверяем результат",
        "SELECT COUNT(*) as total_records FROM product_document;",
        "SELECT id, filename FROM product_document ORDER BY id;"
    ]
    
    # Создаем временный SQL файл
    sql_file = "temp_fix.sql"
    with open(sql_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sql_commands))
    
    print("SQL команды для исправления:")
    for cmd in sql_commands:
        print(f"  {cmd}")
    
    print(f"\nSQL файл создан: {sql_file}")
    print("Выполните эти команды в psql или через админ-панель PostgreSQL")
    
    # Пытаемся выполнить через psql (если доступен)
    try:
        # Формируем команду psql
        db_url = "postgresql://pospro_user:FkfSdSLXtK9ZFei3tch3KmUYuLOeq1rO@dpg-d3fnijili9vc73e7pvq0-a/pospro_db"
        
        # Парсим URL
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        
        psql_cmd = [
            "psql",
            f"--host={parsed.hostname}",
            f"--port={parsed.port}",
            f"--username={parsed.username}",
            f"--dbname={parsed.path[1:]}",
            f"--file={sql_file}"
        ]
        
        print(f"\nКоманда psql: {' '.join(psql_cmd)}")
        print("Установите переменную окружения PGPASSWORD перед выполнением:")
        print(f"export PGPASSWORD='{parsed.password}'")
        
    except Exception as e:
        print(f"Ошибка при формировании команды psql: {e}")

if __name__ == "__main__":
    fix_encoding_direct()
