#!/usr/bin/env python3
"""
Скрипт для тестирования API characteristics_list
"""

import requests
import json

# Базовый URL (замените на ваш)
BASE_URL = "https://pospro-new-server.onrender.com"
# Замените на реальный токен
AUTH_TOKEN = "YOUR_AUTH_TOKEN_HERE"
ADMIN_TOKEN = "YOUR_ADMIN_TOKEN_HERE"

def test_get_characteristics():
    """Тест получения списка характеристик"""
    print("🧪 Тестируем GET /api/characteristics-list...")
    
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    response = requests.get(f"{BASE_URL}/api/characteristics-list", headers=headers)
    
    print(f"Статус: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Успешно! Найдено {len(data.get('data', []))} характеристик")
        return True
    else:
        print(f"❌ Ошибка: {response.text}")
        return False

def test_get_characteristic_by_id():
    """Тест получения характеристики по ID"""
    print("\n🧪 Тестируем GET /api/characteristics-list/1...")
    
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    response = requests.get(f"{BASE_URL}/api/characteristics-list/1", headers=headers)
    
    print(f"Статус: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Успешно! Характеристика: {data.get('data', {}).get('characteristic_key')}")
        return True
    else:
        print(f"❌ Ошибка: {response.text}")
        return False

def test_create_characteristic():
    """Тест создания новой характеристики"""
    print("\n🧪 Тестируем POST /api/characteristics-list...")
    
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "characteristic_key": "ТЕСТ_ХАРАКТЕРИСТИКА",
        "unit_of_measurement": "тест"
    }
    
    response = requests.post(f"{BASE_URL}/api/characteristics-list", 
                           headers=headers, 
                           json=data)
    
    print(f"Статус: {response.status_code}")
    if response.status_code == 201:
        result = response.json()
        print(f"✅ Успешно! Создана характеристика ID: {result.get('data', {}).get('id')}")
        return result.get('data', {}).get('id')
    else:
        print(f"❌ Ошибка: {response.text}")
        return None

def test_update_characteristic(characteristic_id):
    """Тест обновления характеристики"""
    if not characteristic_id:
        print("\n⏭️  Пропускаем тест обновления (нет ID)")
        return False
        
    print(f"\n🧪 Тестируем PUT /api/characteristics-list/{characteristic_id}...")
    
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "characteristic_key": "ОБНОВЛЕННАЯ_ТЕСТ_ХАРАКТЕРИСТИКА",
        "unit_of_measurement": "обновленные_единицы"
    }
    
    response = requests.put(f"{BASE_URL}/api/characteristics-list/{characteristic_id}", 
                           headers=headers, 
                           json=data)
    
    print(f"Статус: {response.status_code}")
    if response.status_code == 200:
        print("✅ Успешно! Характеристика обновлена")
        return True
    else:
        print(f"❌ Ошибка: {response.text}")
        return False

def test_delete_characteristic(characteristic_id):
    """Тест удаления характеристики"""
    if not characteristic_id:
        print("\n⏭️  Пропускаем тест удаления (нет ID)")
        return False
        
    print(f"\n🧪 Тестируем DELETE /api/characteristics-list/{characteristic_id}...")
    
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    response = requests.delete(f"{BASE_URL}/api/characteristics-list/{characteristic_id}", 
                             headers=headers)
    
    print(f"Статус: {response.status_code}")
    if response.status_code == 200:
        print("✅ Успешно! Характеристика удалена")
        return True
    else:
        print(f"❌ Ошибка: {response.text}")
        return False

def main():
    """Запуск всех тестов"""
    print("🚀 Запуск тестов API characteristics_list")
    print("=" * 50)
    
    # Обновляем токены
    print("⚠️  Не забудьте обновить AUTH_TOKEN и ADMIN_TOKEN в скрипте!")
    
    tests_passed = 0
    total_tests = 5
    
    # Тест 1: Получить список
    if test_get_characteristics():
        tests_passed += 1
    
    # Тест 2: Получить по ID
    if test_get_characteristic_by_id():
        tests_passed += 1
    
    # Тест 3: Создать новую
    created_id = test_create_characteristic()
    if created_id:
        tests_passed += 1
    
    # Тест 4: Обновить
    if test_update_characteristic(created_id):
        tests_passed += 1
    
    # Тест 5: Удалить
    if test_delete_characteristic(created_id):
        tests_passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Результаты: {tests_passed}/{total_tests} тестов пройдено")
    
    if tests_passed == total_tests:
        print("🎉 Все тесты пройдены успешно!")
    else:
        print("⚠️  Некоторые тесты не прошли")

if __name__ == "__main__":
    main()
