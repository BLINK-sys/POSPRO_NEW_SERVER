#!/usr/bin/env python3
"""
Миграция для добавления поля description в таблицу homepage_blocks (PostgreSQL)
"""

from flask import Flask
from extensions import db
from sqlalchemy import text

def create_app():
    app = Flask(__name__)
    # Используем PostgreSQL вместо SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://pospro:your_password@localhost/pospro_server_db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def add_description_field():
    """Добавляет поле description в таблицу homepage_blocks"""
    
    app = create_app()
    
    with app.app_context():
        try:
            # Проверяем, существует ли уже поле description
            with db.engine.connect() as connection:
                result = connection.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'homepage_blocks' 
                    AND column_name = 'description'
                """))
                
                if result.fetchone():
                    print("INFO: Поле 'description' уже существует в таблице")
                else:
                    # Добавляем поле description
                    connection.execute(text("""
                        ALTER TABLE homepage_blocks 
                        ADD COLUMN description TEXT
                    """))
                    connection.commit()
                    print("SUCCESS: Поле 'description' успешно добавлено в таблицу 'homepage_blocks'")
                    
        except Exception as e:
            print(f"ERROR: Ошибка при добавлении поля: {e}")

if __name__ == "__main__":
    add_description_field()
