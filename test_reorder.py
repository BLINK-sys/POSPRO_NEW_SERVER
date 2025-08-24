#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функции reorder_media
"""

import requests
import json

# URL сервера
BASE_URL = "http://localhost:5000"

def test_reorder_media():
    """Тестирует функцию reorder_media"""
    
    # Тестовые данные
    product_id = 1  # Замените на реальный ID товара
    media_ids = [1, 2, 3]  # Замените на реальные ID медиа
    
    url = f"{BASE_URL}/upload/media/reorder/{product_id}"
    
    print(f"Тестируем URL: {url}")
    print(f"Данные: {media_ids}")
    
    try:
        response = requests.post(
            url,
            json=media_ids,
            headers={'Content-Type': 'application/json'}
        )
        
        print(f"Статус ответа: {response.status_code}")
        print(f"Заголовки: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("✅ Успешно!")
            print(f"Ответ: {response.json()}")
        else:
            print("❌ Ошибка!")
            print(f"Ответ: {response.text}")
            
    except Exception as e:
        print(f"❌ Исключение: {e}")

if __name__ == "__main__":
    test_reorder_media()

