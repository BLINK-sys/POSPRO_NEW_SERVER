#!/usr/bin/env python3
"""
Миграция для добавления поля description в таблицу homepage_blocks
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

def add_description_field():
    """Добавляет поле description в таблицу homepage_blocks"""
    
    app = create_app()
    
    with app.app_context():
        try:
            # Добавляем поле description
            with db.engine.connect() as connection:
                connection.execute(text("""
                    ALTER TABLE homepage_blocks 
                    ADD COLUMN description TEXT
                """))
                connection.commit()
            
            print("SUCCESS: Поле 'description' успешно добавлено в таблицу 'homepage_blocks'")
            
        except Exception as e:
            print(f"ERROR: Ошибка при добавлении поля: {e}")
            # Проверяем, существует ли уже поле
            try:
                with db.engine.connect() as connection:
                    connection.execute(text("SELECT description FROM homepage_blocks LIMIT 1"))
                print("INFO: Поле 'description' уже существует в таблице")
            except:
                print("ERROR: Поле не существует и не было добавлено")

if __name__ == "__main__":
    add_description_field()
