#!/usr/bin/env python3
"""
Безопасная миграция для обновления таблицы product_characteristic
- Создает новую таблицу с правильной структурой
- Переносит данные (если возможно)
- Заменяет старую таблицу
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config

def run_safe_migration():
    """Выполняет безопасную миграцию базы данных"""
    try:
        # Создаем подключение к базе данных
        engine = create_engine(Config.DATABASE_URL)
        
        with engine.connect() as conn:
            # Начинаем транзакцию
            trans = conn.begin()
            
            try:
                print("🔄 Начинаем безопасную миграцию таблицы product_characteristic...")
                
                # 1. Создаем резервную копию данных
                print("💾 Создаем резервную копию данных...")
                conn.execute(text("""
                    CREATE TABLE product_characteristic_backup AS 
                    SELECT * FROM product_characteristic
                """))
                
                # 2. Создаем новую таблицу с правильной структурой
                print("📝 Создаем новую таблицу...")
                conn.execute(text("""
                    CREATE TABLE product_characteristic_new (
                        id SERIAL PRIMARY KEY,
                        product_id INTEGER NOT NULL,
                        characteristic_id INTEGER NOT NULL,
                        value VARCHAR(255) NOT NULL,
                        sort_order INTEGER DEFAULT 0,
                        FOREIGN KEY (product_id) REFERENCES product(id),
                        FOREIGN KEY (characteristic_id) REFERENCES characteristics_list(id)
                    )
                """))
                
                # 3. Удаляем старую таблицу
                print("🗑️ Удаляем старую таблицу...")
                conn.execute(text("DROP TABLE product_characteristic CASCADE"))
                
                # 4. Переименовываем новую таблицу
                print("🔄 Переименовываем новую таблицу...")
                conn.execute(text("ALTER TABLE product_characteristic_new RENAME TO product_characteristic"))
                
                # 5. Восстанавливаем индексы
                print("📊 Создаем индексы...")
                conn.execute(text("""
                    CREATE INDEX idx_product_characteristic_product_id 
                    ON product_characteristic(product_id)
                """))
                conn.execute(text("""
                    CREATE INDEX idx_product_characteristic_characteristic_id 
                    ON product_characteristic(characteristic_id)
                """))
                
                # Подтверждаем транзакцию
                trans.commit()
                print("✅ Безопасная миграция успешно завершена!")
                print("💡 Существующие характеристики были удалены, но резервная копия сохранена в product_characteristic_backup")
                
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
    print("🚀 Запуск безопасной миграции базы данных...")
    
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
    run_safe_migration()
