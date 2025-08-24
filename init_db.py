#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных PostgreSQL
"""

import os
from app import create_app
from extensions import db

def init_database():
    """Инициализирует базу данных PostgreSQL"""
    try:
        app = create_app()
        
        # Выводим информацию о подключении
        print("🗄️ Информация о подключении к БД:")
        print(f"   DATABASE_URL: {os.getenv('DATABASE_URL', 'Не установлен')}")
        print(f"   SQLALCHEMY_DATABASE_URI: {app.config.get('SQLALCHEMY_DATABASE_URI', 'Не установлен')}")
        
        with app.app_context():
            print("🔧 Создаем таблицы PostgreSQL базы данных...")
            
            # Проверяем подключение к БД
            try:
                db.engine.execute("SELECT 1")
                print("✅ Подключение к базе данных успешно!")
            except Exception as e:
                print(f"❌ Ошибка подключения к БД: {e}")
                return False
            
            # Создаем таблицы
            try:
                db.create_all()
                print("✅ Все таблицы созданы успешно!")
                
                # Проверяем создание основных таблиц
                tables_to_check = ['system_users', 'categories', 'products', 'clients']
                for table in tables_to_check:
                    try:
                        result = db.engine.execute(f"SELECT COUNT(*) FROM {table}")
                        count = result.fetchone()[0]
                        print(f"   ✅ Таблица '{table}': {count} записей")
                    except Exception as e:
                        print(f"   ❌ Таблица '{table}': {e}")
                
                return True
                
            except Exception as e:
                print(f"❌ Ошибка при создании таблиц: {e}")
                return False
                
    except Exception as e:
        print(f"❌ Общая ошибка при инициализации: {e}")
        return False

if __name__ == "__main__":
    success = init_database()
    if success:
        print("🎉 База данных инициализирована успешно!")
        exit(0)
    else:
        print("💥 Ошибка при инициализации базы данных!")
        exit(1)
