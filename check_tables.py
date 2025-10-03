#!/usr/bin/env python3
"""
Проверка существующих таблиц в базе данных
"""

from flask import Flask
from extensions import db
from sqlalchemy import text

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pospro.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def check_tables():
    """Проверяет какие таблицы существуют в базе данных"""
    
    app = create_app()
    
    with app.app_context():
        try:
            with db.engine.connect() as connection:
                result = connection.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' 
                    ORDER BY name
                """))
                
                tables = result.fetchall()
                print("Существующие таблицы:")
                for table in tables:
                    print(f"  - {table[0]}")
                    
                # Проверяем структуру homepage_blocks если таблица существует
                homepage_blocks_exists = any('homepage_blocks' in table[0] for table in tables)
                if homepage_blocks_exists:
                    print("\nСтруктура таблицы homepage_blocks:")
                    result = connection.execute(text("PRAGMA table_info(homepage_blocks)"))
                    columns = result.fetchall()
                    for column in columns:
                        print(f"  - {column[1]} ({column[2]})")
                else:
                    print("\nТаблица homepage_blocks не найдена")
                    
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    check_tables()
