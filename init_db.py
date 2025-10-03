#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных на Render
"""
import os
from flask import Flask
from config import Config
from extensions import db

def init_database():
    """Инициализация базы данных"""
    
    # Создаем минимальное приложение только для инициализации БД
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = Config.SQLALCHEMY_TRACK_MODIFICATIONS
    
    db.init_app(app)
    
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Database initialized successfully!")
        
        # Проверяем, что таблицы созданы
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"Created tables: {len(tables)}")
        for table in tables:
            print(f"  - {table}")

if __name__ == "__main__":
    init_database()
