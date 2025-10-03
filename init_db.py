#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных на Render
"""
import os
from app import create_app
from extensions import db

def init_database():
    """Инициализация базы данных"""
    app = create_app()
    
    with app.app_context():
        print("🔧 Создание таблиц базы данных...")
        db.create_all()
        print("✅ База данных успешно инициализирована!")
        
        # Проверяем, что таблицы созданы
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"📊 Создано таблиц: {len(tables)}")
        for table in tables:
            print(f"  - {table}")

if __name__ == "__main__":
    init_database()
