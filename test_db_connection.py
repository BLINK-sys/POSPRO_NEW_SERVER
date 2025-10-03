#!/usr/bin/env python3
"""
Тестовый скрипт для проверки подключения к базе данных
"""
import os
import psycopg2
from sqlalchemy import create_engine

def test_connection():
    # Получаем URL из переменной окружения
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ DATABASE_URL не установлена")
        return False
    
    print(f"🔍 Тестируем подключение к: {database_url}")
    
    try:
        # Тест 1: Прямое подключение через psycopg2
        print("\n1️⃣ Тест psycopg2...")
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"✅ psycopg2 подключение успешно: {version[0]}")
        cursor.close()
        conn.close()
        
        # Тест 2: Подключение через SQLAlchemy
        print("\n2️⃣ Тест SQLAlchemy...")
        engine = create_engine(database_url)
        with engine.connect() as connection:
            result = connection.execute("SELECT 1")
            print("✅ SQLAlchemy подключение успешно")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return False

if __name__ == "__main__":
    test_connection()
