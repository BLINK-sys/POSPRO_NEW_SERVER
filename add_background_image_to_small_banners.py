#!/usr/bin/env python3
"""
Миграция для добавления поля background_image_url в таблицу small_banners
"""

from flask import Flask
from extensions import db
from sqlalchemy import text

def create_app():
    app = Flask(__name__)
    # Используем PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://pospro:your_password@localhost/pospro_server_db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def add_background_image_field():
    """Добавляет поле background_image_url в таблицу small_banners"""
    
    app = create_app()
    
    with app.app_context():
        try:
            # Проверяем, существует ли уже поле background_image_url
            with db.engine.connect() as connection:
                result = connection.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'small_banners' 
                    AND column_name = 'background_image_url'
                """))
                
                if result.fetchone():
                    print("INFO: Поле 'background_image_url' уже существует в таблице")
                else:
                    # Добавляем поле background_image_url
                    connection.execute(text("""
                        ALTER TABLE small_banners 
                        ADD COLUMN background_image_url VARCHAR(255)
                    """))
                    connection.commit()
                    print("SUCCESS: Поле 'background_image_url' успешно добавлено в таблицу 'small_banners'")
                    
        except Exception as e:
            print(f"ERROR: Ошибка при добавлении поля: {e}")

if __name__ == "__main__":
    add_background_image_field()
