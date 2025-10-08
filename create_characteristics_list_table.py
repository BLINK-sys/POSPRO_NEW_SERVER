#!/usr/bin/env python3
"""
Скрипт для создания таблицы characteristics_list в базе данных PostgreSQL на Render
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def create_characteristics_list_table():
    """Создает таблицу characteristics_list в базе данных"""
    
    # Данные подключения к PostgreSQL на Render
    DATABASE_URL = "postgresql://pospro_user:KVW08syqkUieI32LnEzPZELaSW38cfN8@dpg-d3frm3vfte5s73djh020-a.frankfurt-postgres.render.com/pospro_server_db_qsk1"
    
    try:
        # Подключение к базе данных
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        print("Подключение к базе данных установлено")
        
        # SQL для создания таблицы characteristics_list
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS characteristics_list (
            id SERIAL PRIMARY KEY,
            characteristic_key VARCHAR(100) NOT NULL UNIQUE,
            unit_of_measurement VARCHAR(50)
        );
        """
        
        cursor.execute(create_table_sql)
        print("Таблица characteristics_list создана успешно")
        
        # Добавляем начальные данные
        initial_data = [
            ("ВЕС", "кг"),
            ("ДЛИНА", "см"),
            ("ШИРИНА", "см"),
            ("ВЫСОТА", "см"),
            ("ОБЪЕМ", "л"),
            ("МОЩНОСТЬ", "Вт"),
            ("НАПРЯЖЕНИЕ", "В"),
            ("ТОК", "А"),
            ("ЧАСТОТА", "Гц"),
            ("ТЕМПЕРАТУРА", "°C"),
            ("ДАВЛЕНИЕ", "Па"),
            ("СКОРОСТЬ", "м/с"),
            ("ВРЕМЯ", "ч"),
            ("РАЗМЕР", None),
            ("ЦВЕТ", None),
            ("МАТЕРИАЛ", None),
            ("ТИП", None),
            ("МОДЕЛЬ", None),
            ("ВЕРСИЯ", None),
            ("СЕРИЯ", None)
        ]
        
        insert_sql = """
        INSERT INTO characteristics_list (characteristic_key, unit_of_measurement) 
        VALUES (%s, %s)
        ON CONFLICT (characteristic_key) DO NOTHING;
        """
        
        for key, unit in initial_data:
            cursor.execute(insert_sql, (key, unit))
        
        print(f"Добавлено {len(initial_data)} записей в справочник характеристик")
        
        # Проверяем созданную таблицу
        cursor.execute("SELECT COUNT(*) FROM characteristics_list;")
        count = cursor.fetchone()[0]
        print(f"Всего записей в таблице: {count}")
        
        # Показываем первые несколько записей
        cursor.execute("SELECT * FROM characteristics_list ORDER BY id LIMIT 5;")
        records = cursor.fetchall()
        print("\nПервые записи:")
        for record in records:
            print(f"ID: {record[0]}, Ключ: {record[1]}, Единица: {record[2] or 'Не указана'}")
        
        cursor.close()
        conn.close()
        print("\nОперация завершена успешно!")
        
    except psycopg2.Error as e:
        print(f"Ошибка PostgreSQL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Общая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_characteristics_list_table()
