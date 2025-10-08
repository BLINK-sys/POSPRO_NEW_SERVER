#!/usr/bin/env python3
"""
Скрипт для добавления поля open_in_new_tab в таблицу small_banners на Render
"""

import psycopg2
import sys

# Строка подключения к базе данных Render
DATABASE_URL = "postgresql://pospro_user:KVW08syqkUieI32LnEzPZELaSW38cfN8@dpg-d3frm3vfte5s73djh020-a.frankfurt-postgres.render.com/pospro_server_db_qsk1"

def add_small_banner_fields():
    """Добавляет поле open_in_new_tab в таблицу small_banners"""
    
    try:
        # Подключаемся к базе данных
        print("Подключаемся к базе данных Render...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Проверяем текущие колонки
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'small_banners'
        """)
        columns = [row[0] for row in cursor.fetchall()]
        print(f"Текущие колонки в таблице small_banners: {columns}")
        
        # Добавляем колонку open_in_new_tab
        if 'open_in_new_tab' not in columns:
            print("Добавляем колонку open_in_new_tab...")
            cursor.execute("ALTER TABLE small_banners ADD COLUMN open_in_new_tab BOOLEAN DEFAULT FALSE")
            conn.commit()
            print("Колонка open_in_new_tab добавлена")
        else:
            print("Колонка open_in_new_tab уже существует")
        
        # Проверяем результат
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'small_banners'
        """)
        columns = [row[0] for row in cursor.fetchall()]
        print(f"\nКолонки после миграции: {columns}")
        
        cursor.close()
        conn.close()
        
        print("\nМиграция завершена успешно!")
        return True
        
    except Exception as e:
        print(f"Ошибка при выполнении миграции: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    success = add_small_banner_fields()
    sys.exit(0 if success else 1)
