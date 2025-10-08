#!/usr/bin/env python3
"""
Скрипт для создания таблицы characteristics_list в продакшн базе Render
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

def create_characteristics_list_production():
    """Создает таблицу characteristics_list в продакшн базе"""
    
    # Получаем URL базы данных из переменных окружения Render
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL не найден в переменных окружения")
        print("Убедитесь, что вы запускаете скрипт на Render или установили DATABASE_URL")
        return False
    
    print(f"Подключение к базе данных: {database_url[:20]}...")
    
    # Создаем подключение к базе данных
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as connection:
            # SQL для создания таблицы characteristics_list
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS characteristics_list (
                id SERIAL PRIMARY KEY,
                characteristic_key VARCHAR(100) NOT NULL UNIQUE,
                unit_of_measurement VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
            
            # Выполняем создание таблицы
            connection.execute(text(create_table_sql))
            connection.commit()
            
            print("SUCCESS: Таблица characteristics_list успешно создана в продакшн базе")
            
            # Добавляем начальные данные
            insert_data_sql = """
            INSERT INTO characteristics_list (characteristic_key, unit_of_measurement) VALUES
            ('ВЕС', 'кг'),
            ('ДЛИНА', 'см'),
            ('ШИРИНА', 'см'),
            ('ВЫСОТА', 'см'),
            ('ОБЪЕМ', 'л'),
            ('МОЩНОСТЬ', 'Вт'),
            ('НАПРЯЖЕНИЕ', 'В'),
            ('ТОК', 'А'),
            ('ЧАСТОТА', 'Гц'),
            ('ТЕМПЕРАТУРА', '°C')
            ON CONFLICT (characteristic_key) DO NOTHING;
            """
            
            connection.execute(text(insert_data_sql))
            connection.commit()
            
            print("SUCCESS: Начальные данные добавлены в продакшн базу")
            
    except SQLAlchemyError as e:
        print(f"ERROR: Ошибка при создании таблицы: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Неожиданная ошибка: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("Создание таблицы characteristics_list в продакшн базе...")
    success = create_characteristics_list_production()
    
    if success:
        print("SUCCESS: Процесс завершен успешно!")
    else:
        print("ERROR: Процесс завершен с ошибками!")
        sys.exit(1)
