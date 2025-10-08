#!/usr/bin/env python3
"""
Скрипт для заполнения таблицы characteristics_list начальными данными
"""

import os
import sys
from dotenv import load_dotenv

# Добавляем текущую директорию в путь Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Загружаем переменные окружения только для локальной разработки
if not os.getenv("RENDER"):
    load_dotenv()

from app import create_app
from extensions import db
from models.characteristics_list import CharacteristicsList

def seed_characteristics_list():
    """Заполняет таблицу characteristics_list начальными данными"""
    app = create_app()
    
    with app.app_context():
        try:
            # Проверяем, есть ли уже данные
            existing_count = CharacteristicsList.query.count()
            if existing_count > 0:
                print(f"⚠️  В таблице characteristics_list уже есть {existing_count} записей")
                return True
            
            # Начальные данные
            characteristics_data = [
                {"characteristic_key": "ВЕС", "unit_of_measurement": "кг"},
                {"characteristic_key": "ДЛИНА", "unit_of_measurement": "см"},
                {"characteristic_key": "ШИРИНА", "unit_of_measurement": "см"},
                {"characteristic_key": "ВЫСОТА", "unit_of_measurement": "см"},
                {"characteristic_key": "ОБЪЕМ", "unit_of_measurement": "л"},
                {"characteristic_key": "МОЩНОСТЬ", "unit_of_measurement": "Вт"},
                {"characteristic_key": "НАПРЯЖЕНИЕ", "unit_of_measurement": "В"},
                {"characteristic_key": "ТОК", "unit_of_measurement": "А"},
                {"characteristic_key": "ЧАСТОТА", "unit_of_measurement": "Гц"},
                {"characteristic_key": "ТЕМПЕРАТУРА", "unit_of_measurement": "°C"},
                {"characteristic_key": "ВЛАЖНОСТЬ", "unit_of_measurement": "%"},
                {"characteristic_key": "ДАВЛЕНИЕ", "unit_of_measurement": "Па"},
                {"characteristic_key": "СКОРОСТЬ", "unit_of_measurement": "м/с"},
                {"characteristic_key": "ВРЕМЯ", "unit_of_measurement": "сек"},
                {"characteristic_key": "РАССТОЯНИЕ", "unit_of_measurement": "м"},
                {"characteristic_key": "ПЛОЩАДЬ", "unit_of_measurement": "м²"},
                {"characteristic_key": "ЦВЕТ", "unit_of_measurement": None},
                {"characteristic_key": "МАТЕРИАЛ", "unit_of_measurement": None},
                {"characteristic_key": "ПРОИЗВОДИТЕЛЬ", "unit_of_measurement": None},
                {"characteristic_key": "МОДЕЛЬ", "unit_of_measurement": None},
            ]
            
            # Добавляем данные
            for data in characteristics_data:
                characteristic = CharacteristicsList(
                    characteristic_key=data["characteristic_key"],
                    unit_of_measurement=data["unit_of_measurement"]
                )
                db.session.add(characteristic)
            
            db.session.commit()
            print(f"✅ Добавлено {len(characteristics_data)} записей в characteristics_list")
            
            # Показываем добавленные данные
            all_characteristics = CharacteristicsList.query.all()
            print("\n📋 Добавленные характеристики:")
            for char in all_characteristics:
                unit = f" ({char.unit_of_measurement})" if char.unit_of_measurement else ""
                print(f"  - {char.characteristic_key}{unit}")
                
        except Exception as e:
            print(f"❌ Ошибка при заполнении таблицы: {e}")
            db.session.rollback()
            return False
    
    return True

if __name__ == "__main__":
    print("Заполнение таблицы characteristics_list начальными данными...")
    success = seed_characteristics_list()
    
    if success:
        print("🎉 Готово!")
    else:
        print("💥 Произошла ошибка!")
        sys.exit(1)
