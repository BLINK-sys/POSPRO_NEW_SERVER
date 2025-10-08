#!/usr/bin/env python3
"""
Скрипт для развертывания таблицы characteristics_list на Render
Запускается автоматически при деплое
"""

import os
import sys
import subprocess

def deploy_characteristics_list():
    """Запускает создание таблицы characteristics_list на Render"""
    
    print("🚀 Начинаем развертывание справочника характеристик...")
    
    try:
        # Запускаем скрипт создания таблицы
        result = subprocess.run([
            sys.executable, 
            'create_characteristics_list_table.py'
        ], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        
        if result.returncode == 0:
            print("✅ Справочник характеристик успешно развернут!")
            print("📊 Результат выполнения:")
            print(result.stdout)
        else:
            print("❌ Ошибка при развертывании справочника характеристик:")
            print(result.stderr)
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    deploy_characteristics_list()
