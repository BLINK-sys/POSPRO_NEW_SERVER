#!/usr/bin/env python3
"""
Создание всех таблиц в базе данных
"""

from flask import Flask
from extensions import db
from models.homepage_block import HomepageBlock
from models.homepage_block_title import HomepageBlockItem

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pospro.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def create_all_tables():
    """Создает все таблицы в базе данных"""
    
    app = create_app()
    
    with app.app_context():
        try:
            # Создаем все таблицы
            db.create_all()
            print("SUCCESS: Все таблицы успешно созданы")
            
            # Проверяем создание таблицы homepage_blocks
            from sqlalchemy import text
            with db.engine.connect() as connection:
                result = connection.execute(text("PRAGMA table_info(homepage_blocks)"))
                columns = result.fetchall()
                print("\nСтруктура таблицы homepage_blocks:")
                for column in columns:
                    print(f"  - {column[1]} ({column[2]})")
                    
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    create_all_tables()
