#!/usr/bin/env python3
"""
Скрипт для запуска сервера в режиме локальной разработки
"""
import os
import sys
from app import create_app

def main():
    print("🚀 Запуск PosPro Server в режиме локальной разработки...")
    
    # Устанавливаем переменную окружения для локальной разработки
    os.environ.setdefault('FLASK_ENV', 'development')
    
    # Создаем приложение
    app = create_app()
    
    # Запускаем сервер
    print("📡 Сервер запущен на http://localhost:5000")
    print("🛑 Для остановки нажмите Ctrl+C")
    
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=True
    )

if __name__ == "__main__":
    main()
