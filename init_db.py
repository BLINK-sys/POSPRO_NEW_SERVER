#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных PostgreSQL
"""

from app import create_app
from extensions import db

def init_database():
    """Инициализирует базу данных PostgreSQL"""
    app = create_app()
    
    with app.app_context():
        print("🗄️ Создаем таблицы PostgreSQL базы данных...")
        try:
            db.create_all()
            print("✅ PostgreSQL база данных инициализирована успешно!")
        except Exception as e:
            print(f"❌ Ошибка при инициализации базы данных: {e}")
            print("💡 Убедитесь, что DATABASE_URL настроен правильно")

if __name__ == "__main__":
    init_database()
