#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных
"""

from app import create_app
from extensions import db

def init_database():
    """Инициализирует базу данных"""
    app = create_app()
    
    with app.app_context():
        print("🗄️ Создаем таблицы базы данных...")
        db.create_all()
        print("✅ База данных инициализирована успешно!")

if __name__ == "__main__":
    init_database()
