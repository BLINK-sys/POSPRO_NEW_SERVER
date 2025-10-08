#!/usr/bin/env python3
"""
Тестирование API справочника характеристик
"""

import requests
import json

# Базовый URL API
BASE_URL = "http://127.0.0.1:5000"

def login_admin():
    """Авторизация админа"""
    login_data = {
        "email": "bocan.anton@mail.ru",
        "password": "1"
    }
    
    response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    if response.status_code == 200:
        data = response.json()
        if data.get('success'):
            return data['data']['access_token']
    return None

def test_get_characteristics_list(token):
    """Тест получения списка характеристик"""
    print("🔍 Тестирование получения списка характеристик...")
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/characteristics-list", headers=headers)
    
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()

def test_create_characteristic(token):
    """Тест создания характеристики"""
    print("➕ Тестирование создания характеристики...")
    
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "characteristic_key": "ВЕС",
        "unit_of_measurement": "кг"
    }
    
    response = requests.post(f"{BASE_URL}/characteristics-list", json=data, headers=headers)
    
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()
    
    return response.json().get('data', {}).get('id') if response.status_code == 201 else None

def test_create_characteristic_without_unit(token):
    """Тест создания характеристики без единицы измерения"""
    print("➕ Тестирование создания характеристики без единицы измерения...")
    
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "characteristic_key": "ЦВЕТ"
    }
    
    response = requests.post(f"{BASE_URL}/characteristics-list", json=data, headers=headers)
    
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()
    
    return response.json().get('data', {}).get('id') if response.status_code == 201 else None

def test_get_characteristic(token, characteristic_id):
    """Тест получения характеристики по ID"""
    print(f"🔍 Тестирование получения характеристики ID {characteristic_id}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/characteristics-list/{characteristic_id}", headers=headers)
    
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()

def test_update_characteristic(token, characteristic_id):
    """Тест обновления характеристики"""
    print(f"✏️ Тестирование обновления характеристики ID {characteristic_id}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "characteristic_key": "ВЕС_ОБНОВЛЕН",
        "unit_of_measurement": "г"
    }
    
    response = requests.put(f"{BASE_URL}/characteristics-list/{characteristic_id}", json=data, headers=headers)
    
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()

def test_delete_characteristic(token, characteristic_id):
    """Тест удаления характеристики"""
    print(f"🗑️ Тестирование удаления характеристики ID {characteristic_id}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.delete(f"{BASE_URL}/characteristics-list/{characteristic_id}", headers=headers)
    
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()

def main():
    print("Начинаем тестирование API справочника характеристик")
    print("=" * 60)
    
    # Авторизация
    token = login_admin()
    if not token:
        print("Ошибка авторизации!")
        return
    
    print("Авторизация успешна")
    print()
    
    # Тест получения списка (должен быть пустым)
    test_get_characteristics_list(token)
    
    # Тест создания характеристик
    weight_id = test_create_characteristic(token)
    color_id = test_create_characteristic_without_unit(token)
    
    # Тест получения списка (должен содержать созданные характеристики)
    test_get_characteristics_list(token)
    
    # Тест получения конкретной характеристики
    if weight_id:
        test_get_characteristic(token, weight_id)
    
    # Тест обновления характеристики
    if weight_id:
        test_update_characteristic(token, weight_id)
        test_get_characteristic(token, weight_id)
    
    # Тест удаления характеристик
    if weight_id:
        test_delete_characteristic(token, weight_id)
    if color_id:
        test_delete_characteristic(token, color_id)
    
    # Финальный список (должен быть пустым)
    test_get_characteristics_list(token)
    
    print("Тестирование завершено!")

if __name__ == "__main__":
    main()
