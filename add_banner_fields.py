#!/usr/bin/env python3
"""
Скрипт для добавления новых полей в таблицу banners
"""

import os
import sys
from flask import Flask
from extensions import db
from models.banner import Banner
from config import Config

def add_banner_fields():
    """Добавляет новые поля в таблицу banners"""
    
    # Создаем приложение Flask
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Инициализируем расширения
    db.init_app(app)
    
    with app.app_context():
        try:
            # Проверяем, существуют ли уже новые колонки
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('banners')]
            
            print(f"Текущие колонки в таблице banners: {columns}")
            
            # Добавляем новые колонки, если их нет
            if 'open_in_new_tab' not in columns:
                print("Добавляем колонку open_in_new_tab...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE banners ADD COLUMN open_in_new_tab BOOLEAN DEFAULT FALSE"))
                    conn.commit()
                print("Колонка open_in_new_tab добавлена")
            else:
                print("Колонка open_in_new_tab уже существует")
                
            if 'button_color' not in columns:
                print("Добавляем колонку button_color...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE banners ADD COLUMN button_color VARCHAR(7) DEFAULT '#000000'"))
                    conn.commit()
                print("Колонка button_color добавлена")
            else:
                print("Колонка button_color уже существует")
                
            if 'button_text_color' not in columns:
                print("Добавляем колонку button_text_color...")
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE banners ADD COLUMN button_text_color VARCHAR(7) DEFAULT '#ffffff'"))
                    conn.commit()
                print("Колонка button_text_color добавлена")
            else:
                print("Колонка button_text_color уже существует")
                
            print("\nМиграция завершена успешно!")
            
        except Exception as e:
            print(f"Ошибка при выполнении миграции: {e}")
            return False
            
    return True

if __name__ == "__main__":
    success = add_banner_fields()
    sys.exit(0 if success else 1)
