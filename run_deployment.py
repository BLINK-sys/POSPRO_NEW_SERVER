#!/usr/bin/env python3
"""
Скрипт для запуска развертывания characteristics_list на Render
Используется в Procfile для автоматического развертывания при деплое
"""

import os
import sys
import subprocess

def run_deployment():
    """Запускает развертывание characteristics_list"""
    try:
        print("🚀 Запуск развертывания characteristics_list...")
        
        # Запускаем скрипт развертывания
        result = subprocess.run([
            sys.executable, 
            "deploy_characteristics_list.py"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Развертывание characteristics_list завершено успешно")
            print(result.stdout)
        else:
            print("❌ Ошибка при развертывании characteristics_list")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = run_deployment()
    if not success:
        sys.exit(1)
