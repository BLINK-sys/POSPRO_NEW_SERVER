#!/usr/bin/env python3
"""
Скрипт для развертывания таблицы characteristics_list на Render
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

def deploy_characteristics_list():
    """Развертывает таблицу characteristics_list на Render"""
    app = create_app()
    
    with app.app_context():
        try:
            print("🚀 Начинаем развертывание characteristics_list на Render...")
            
            # Создаем таблицу
            db.create_all()
            print("✅ Таблица characteristics_list создана/обновлена")
            
            # Проверяем, есть ли уже данные
            existing_count = CharacteristicsList.query.count()
            print(f"📊 Текущее количество записей: {existing_count}")
            
            if existing_count == 0:
                print("🌱 Заполняем таблицу начальными данными...")
                
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
                print(f"✅ Добавлено {len(characteristics_data)} записей")
            else:
                print("ℹ️  Таблица уже содержит данные, пропускаем заполнение")
            
            # Финальная проверка
            final_count = CharacteristicsList.query.count()
            print(f"🎉 Развертывание завершено! Всего записей: {final_count}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка при развертывании: {e}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    print("🚀 Развертывание characteristics_list на Render...")
    success = deploy_characteristics_list()
    
    if success:
        print("🎉 Развертывание успешно завершено!")
    else:
        print("💥 Произошла ошибка при развертывании!")
        sys.exit(1)
