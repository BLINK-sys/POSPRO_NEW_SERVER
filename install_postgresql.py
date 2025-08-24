#!/usr/bin/env python3
"""
Скрипт для установки правильного PostgreSQL драйвера для Python 3.13
"""

import subprocess
import sys

def install_package(package):
    """Устанавливает пакет через pip"""
    try:
        print(f"📦 Устанавливаем {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка установки {package}: {e}")
        return False

def test_import(module_name):
    """Тестирует импорт модуля"""
    try:
        __import__(module_name)
        print(f"✅ {module_name} успешно импортирован")
        return True
    except ImportError as e:
        print(f"❌ Ошибка импорта {module_name}: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка при импорте {module_name}: {e}")
        return False

def main():
    print("🔧 Устанавливаем PostgreSQL драйвер для Python 3.13...")
    
    # Сначала пробуем psycopg2-binary с новой версией
    if install_package("psycopg2-binary==2.9.9"):
        if test_import("psycopg2"):
            print("✅ psycopg2-binary==2.9.9 установлен и работает")
            return
    
    # Если не получилось, пробуем psycopg2
    if install_package("psycopg2==2.9.9"):
        if test_import("psycopg2"):
            print("✅ psycopg2==2.9.9 установлен и работает")
            return
    
    # Если и это не работает, пробуем psycopg2-binary с более старой версией
    if install_package("psycopg2-binary==2.9.7"):
        if test_import("psycopg2"):
            print("✅ psycopg2-binary==2.9.7 установлен и работает")
            return
    
    # Последний вариант - asyncpg
    if install_package("asyncpg==0.29.0"):
        if test_import("asyncpg"):
            print("✅ asyncpg==0.29.0 установлен и работает")
            return
    
    print("❌ Не удалось установить ни один PostgreSQL драйвер")
    print("💡 Попробуем использовать psycopg2-binary==2.9.7 как fallback...")
    
    # Fallback - используем последний установленный драйвер
    try:
        import psycopg2
        print("✅ Используем psycopg2-binary==2.9.7 как fallback")
        return
    except ImportError:
        print("❌ Даже fallback не работает")
        sys.exit(1)

if __name__ == "__main__":
    main()
