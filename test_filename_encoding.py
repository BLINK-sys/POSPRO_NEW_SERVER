#!/usr/bin/env python3
"""
Тест для проверки кодировки имен файлов в базе данных
"""
import os
from app import create_app
from extensions import db
from models.documents import ProductDocument

def test_filename_encoding():
    """Тестируем кодировку имен файлов"""
    app = create_app()
    
    with app.app_context():
        # Получаем все документы и драйверы
        docs = ProductDocument.query.all()
        
        print("=== АНАЛИЗ КОДИРОВКИ ИМЕН ФАЙЛОВ ===")
        print(f"Найдено записей: {len(docs)}")
        print()
        
        for doc in docs:
            print(f"ID: {doc.id}")
            print(f"Product ID: {doc.product_id}")
            print(f"Filename (raw): {repr(doc.filename)}")
            print(f"Filename (display): {doc.filename}")
            print(f"Filename bytes: {doc.filename.encode('utf-8')}")
            print(f"File type: {doc.file_type}")
            print(f"URL: {doc.url}")
            print("-" * 50)
        
        # Проверяем кодировку базы данных
        print("\n=== ПРОВЕРКА КОДИРОВКИ БД ===")
        result = db.session.execute(db.text("SHOW client_encoding")).fetchone()
        print(f"Client encoding: {result[0] if result else 'Unknown'}")
        
        result = db.session.execute(db.text("SHOW server_encoding")).fetchone()
        print(f"Server encoding: {result[0] if result else 'Unknown'}")

if __name__ == "__main__":
    test_filename_encoding()
