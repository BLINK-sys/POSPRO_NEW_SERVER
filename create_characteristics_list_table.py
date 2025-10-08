#!/usr/bin/env python3
"""
Скрипт для создания таблицы characteristics_list в базе данных
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

def create_characteristics_list_table():
    """Создает таблицу characteristics_list"""
    app = create_app()
    
    with app.app_context():
        try:
            # Создаем таблицу
            db.create_all()
            print("✅ Таблица characteristics_list создана успешно!")
            
            # Проверяем, что таблица создалась
            result = db.engine.execute("SELECT to_regclass('characteristics_list')")
            table_exists = result.fetchone()[0] is not None
            
            if table_exists:
                print("✅ Таблица characteristics_list существует в базе данных")
            else:
                print("❌ Таблица characteristics_list не найдена")
                
        except Exception as e:
            print(f"❌ Ошибка при создании таблицы: {e}")
            return False
    
    return True

if __name__ == "__main__":
    print("Создание таблицы characteristics_list...")
    success = create_characteristics_list_table()
    
    if success:
        print("🎉 Готово!")
    else:
        print("💥 Произошла ошибка!")
        sys.exit(1)
