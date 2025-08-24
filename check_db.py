#!/usr/bin/env python3
"""
Скрипт для проверки состояния базы данных
"""

import os
from app import create_app
from extensions import db
import models

def check_database():
    """Проверяет состояние базы данных"""
    try:
        app = create_app()
        
        print("🔍 Проверка состояния базы данных...")
        print(f"   DATABASE_URL: {os.getenv('DATABASE_URL', 'Не установлен')}")
        print(f"   SQLALCHEMY_DATABASE_URI: {app.config.get('SQLALCHEMY_DATABASE_URI', 'Не установлен')}")
        
        with app.app_context():
            # Проверяем подключение
            try:
                db.engine.execute("SELECT 1")
                print("✅ Подключение к БД успешно!")
            except Exception as e:
                print(f"❌ Ошибка подключения к БД: {e}")
                return False
            
            # Проверяем таблицы
            tables_to_check = ['system_users', 'categories', 'products', 'clients']
            for table in tables_to_check:
                try:
                    result = db.engine.execute(f"SELECT COUNT(*) FROM {table}")
                    count = result.fetchone()[0]
                    print(f"   ✅ Таблица '{table}': {count} записей")
                except Exception as e:
                    print(f"   ❌ Таблица '{table}': {e}")
            
            # Проверяем системного пользователя
            try:
                from models.systemuser import SystemUser
                user = SystemUser.query.filter_by(email='bocan.anton@mail.ru').first()
                if user:
                    print(f"   ✅ Системный пользователь найден: {user.full_name}")
                else:
                    print("   ❌ Системный пользователь не найден")
            except Exception as e:
                print(f"   ❌ Ошибка при поиске пользователя: {e}")
            
            return True
            
    except Exception as e:
        print(f"❌ Общая ошибка: {e}")
        return False

if __name__ == "__main__":
    check_database()
