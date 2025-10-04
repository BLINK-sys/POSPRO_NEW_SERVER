#!/usr/bin/env python3
"""
Отладка обработки имен файлов при загрузке
"""
import os
from werkzeug.datastructures import FileStorage
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

def debug_filename_handling():
    """Тестируем обработку имен файлов"""
    
    # Симулируем загрузку файла с русским именем
    test_filename = "Документ Microsoft Word.docx"
    
    print("=== ОТЛАДКА ОБРАБОТКИ ИМЕН ФАЙЛОВ ===")
    print(f"Исходное имя файла: {test_filename}")
    print(f"Байты исходного имени: {test_filename.encode('utf-8')}")
    
    # Создаем тестовый файл
    builder = EnvironBuilder(
        method='POST',
        data={'file': (open('test_file.txt', 'w', encoding='utf-8').write('test'), test_filename)}
    )
    
    # Тестируем разные способы получения имени файла
    print("\n=== ТЕСТИРОВАНИЕ РАЗНЫХ КОДИРОВОК ===")
    
    # UTF-8
    try:
        utf8_bytes = test_filename.encode('utf-8')
        print(f"UTF-8 байты: {utf8_bytes}")
        print(f"UTF-8 декодирование: {utf8_bytes.decode('utf-8')}")
    except Exception as e:
        print(f"UTF-8 ошибка: {e}")
    
    # Windows-1251
    try:
        cp1251_bytes = test_filename.encode('cp1251')
        print(f"CP1251 байты: {cp1251_bytes}")
        print(f"CP1251 декодирование: {cp1251_bytes.decode('cp1251')}")
    except Exception as e:
        print(f"CP1251 ошибка: {e}")
    
    # Latin1
    try:
        latin1_bytes = test_filename.encode('latin1')
        print(f"Latin1 байты: {latin1_bytes}")
        print(f"Latin1 декодирование: {latin1_bytes.decode('latin1')}")
    except Exception as e:
        print(f"Latin1 ошибка: {e}")
    
    # Тестируем искаженное имя
    corrupted = "ĐĐ¼Ð°Ñ Ð¼ÐµÐ½Ñ_Microsoft_Word.docx"
    print(f"\nИскаженное имя: {corrupted}")
    print(f"Байты искаженного имени: {corrupted.encode('utf-8')}")
    
    # Пытаемся исправить
    print("\n=== ПОПЫТКИ ИСПРАВЛЕНИЯ ===")
    try:
        # Декодируем как UTF-8, затем кодируем как latin1, затем декодируем как cp1251
        fixed = corrupted.encode('utf-8').decode('latin1').encode('cp1251').decode('utf-8')
        print(f"Исправленное имя: {fixed}")
    except Exception as e:
        print(f"Ошибка исправления: {e}")

if __name__ == "__main__":
    debug_filename_handling()
