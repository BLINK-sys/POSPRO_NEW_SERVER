#!/usr/bin/env python3
"""
Миграция для обновления таблицы product_characteristic
- Добавляет колонку characteristic_id
- Удаляет колонку key
- Создает связь с таблицей characteristics_list
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config

def run_migration():
    """Выполняет миграцию базы данных"""
    try:
        # Создаем подключение к базе данных
        engine = create_engine(Config.DATABASE_URL)
        
        with engine.connect() as conn:
            # Начинаем транзакцию
            trans = conn.begin()
            
            try:
                print("🔄 Начинаем миграцию таблицы product_characteristic...")
                
                # 1. Добавляем новую колонку characteristic_id
                print("📝 Добавляем колонку characteristic_id...")
                conn.execute(text("""
                    ALTER TABLE product_characteristic 
                    ADD COLUMN characteristic_id INTEGER
                """))
                
                # 2. Создаем внешний ключ (если таблица characteristics_list существует)
                print("🔗 Создаем внешний ключ...")
                conn.execute(text("""
                    ALTER TABLE product_characteristic 
                    ADD CONSTRAINT fk_product_characteristic_characteristic_id 
                    FOREIGN KEY (characteristic_id) REFERENCES characteristics_list(id)
                """))
                
                # 3. Удаляем старую колонку key
                print("🗑️ Удаляем старую колонку key...")
                conn.execute(text("""
                    ALTER TABLE product_characteristic 
                    DROP COLUMN key
                """))
                
                # Подтверждаем транзакцию
                trans.commit()
                print("✅ Миграция успешно завершена!")
                
            except SQLAlchemyError as e:
                # Откатываем транзакцию в случае ошибки
                trans.rollback()
                print(f"❌ Ошибка миграции: {e}")
                raise
                
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

def check_table_exists():
    """Проверяет существование таблицы characteristics_list"""
    try:
        engine = create_engine(Config.DATABASE_URL)
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'characteristics_list'
                );
            """))
            exists = result.scalar()
            return exists
    except Exception as e:
        print(f"❌ Ошибка проверки таблицы: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Запуск миграции базы данных...")
    
    # Проверяем существование таблицы characteristics_list
    if not check_table_exists():
        print("❌ Таблица characteristics_list не существует!")
        print("💡 Сначала создайте таблицу characteristics_list через справочник характеристик")
        sys.exit(1)
    
    print("✅ Таблица characteristics_list найдена")
    
    # Запрашиваем подтверждение
    response = input("⚠️  Внимание! Эта миграция удалит все существующие характеристики товаров. Продолжить? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Миграция отменена")
        sys.exit(0)
    
    # Выполняем миграцию
    run_migration()
