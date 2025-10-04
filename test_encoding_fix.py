#!/usr/bin/env python3
"""
Тест различных способов исправления кодировки
"""
import codecs

def test_encoding_fixes():
    """Тестируем разные способы исправления кодировки"""
    
    # Искаженное имя файла
    corrupted = "ÐÐ¾ÐºÑÐ¼ÐµÐ½Ñ_Microsoft_Word.docx"
    expected = "Документ_Microsoft_Word.docx"
    
    print("=== ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЯ КОДИРОВКИ ===")
    print(f"Искаженное: {corrupted}")
    print(f"Ожидаемое: {expected}")
    print(f"Байты искаженного: {corrupted.encode('utf-8')}")
    print()
    
    # Способ 1: UTF-8 → Latin1 → CP1251 → UTF-8
    try:
        fixed1 = corrupted.encode('utf-8').decode('latin1').encode('cp1251').decode('utf-8')
        print(f"Способ 1 (UTF-8→Latin1→CP1251→UTF-8): {fixed1}")
        print(f"Совпадает с ожидаемым: {fixed1 == expected}")
    except Exception as e:
        print(f"Способ 1 ошибка: {e}")
    
    # Способ 2: Прямое декодирование как CP1251
    try:
        fixed2 = corrupted.encode('latin1').decode('cp1251')
        print(f"Способ 2 (Latin1→CP1251): {fixed2}")
        print(f"Совпадает с ожидаемым: {fixed2 == expected}")
    except Exception as e:
        print(f"Способ 2 ошибка: {e}")
    
    # Способ 3: UTF-8 → CP1251
    try:
        fixed3 = corrupted.encode('utf-8').decode('cp1251')
        print(f"Способ 3 (UTF-8→CP1251): {fixed3}")
        print(f"Совпадает с ожидаемым: {fixed3 == expected}")
    except Exception as e:
        print(f"Способ 3 ошибка: {e}")
    
    # Способ 4: Обратное кодирование
    try:
        # Декодируем как UTF-8, затем кодируем как latin1, затем декодируем как cp1251
        fixed4 = codecs.decode(corrupted.encode('utf-8'), 'latin1').decode('cp1251')
        print(f"Способ 4 (codecs): {fixed4}")
        print(f"Совпадает с ожидаемым: {fixed4 == expected}")
    except Exception as e:
        print(f"Способ 4 ошибка: {e}")
    
    # Способ 5: Пошаговое исправление
    try:
        # Сначала декодируем как latin1, затем как cp1251
        step1 = corrupted.encode('utf-8').decode('latin1')
        print(f"Шаг 1 (UTF-8→Latin1): {step1}")
        print(f"Байты шага 1: {step1.encode('utf-8')}")
        
        step2 = step1.encode('latin1').decode('cp1251')
        print(f"Шаг 2 (Latin1→CP1251): {step2}")
        print(f"Совпадает с ожидаемым: {step2 == expected}")
    except Exception as e:
        print(f"Способ 5 ошибка: {e}")
    
    # Способ 6: Прямое исправление через bytes
    try:
        # Получаем байты искаженной строки
        corrupted_bytes = corrupted.encode('utf-8')
        print(f"Байты искаженной строки: {corrupted_bytes}")
        
        # Декодируем как latin1
        latin1_decoded = corrupted_bytes.decode('latin1')
        print(f"Декодировано как latin1: {latin1_decoded}")
        
        # Кодируем как cp1251 и декодируем как utf-8
        fixed6 = latin1_decoded.encode('cp1251').decode('utf-8')
        print(f"Способ 6 (прямое): {fixed6}")
        print(f"Совпадает с ожидаемым: {fixed6 == expected}")
    except Exception as e:
        print(f"Способ 6 ошибка: {e}")

if __name__ == "__main__":
    test_encoding_fixes()
