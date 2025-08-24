#!/usr/bin/env python3
"""
Скрипт для установки правильных зависимостей PostgreSQL
"""

import subprocess
import sys

def install_package(package):
    """Устанавливает пакет через pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    print("🔧 Устанавливаем зависимости PostgreSQL...")
    
    # Сначала пробуем psycopg2-binary
    print("📦 Пробуем установить psycopg2-binary...")
    if install_package("psycopg2-binary==2.9.9"):
        print("✅ psycopg2-binary установлен успешно")
        return
    
    # Если не получилось, пробуем psycopg2
    print("📦 Пробуем установить psycopg2...")
    if install_package("psycopg2==2.9.9"):
        print("✅ psycopg2 установлен успешно")
        return
    
    # Если и это не работает, устанавливаем asyncpg
    print("📦 Устанавливаем asyncpg...")
    if install_package("asyncpg==0.29.0"):
        print("✅ asyncpg установлен успешно")
        return
    
    print("❌ Не удалось установить ни один драйвер PostgreSQL")
    sys.exit(1)

if __name__ == "__main__":
    main()
