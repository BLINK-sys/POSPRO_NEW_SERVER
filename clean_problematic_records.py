#!/usr/bin/env python3
"""
Скрипт для очистки записей с проблемной кодировкой
"""
import os
import sys

# Добавляем путь к проекту
sys.path.append(os.path.dirname(__file__))

def clean_problematic_records():
    """Удаляем записи с проблемной кодировкой"""
    try:
        from flask import Flask
        from config import Config
        from extensions import db
        from models.documents import ProductDocument
        
        # Создаем минимальное приложение
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = Config.SQLALCHEMY_TRACK_MODIFICATIONS
        
        db.init_app(app)
        
        with app.app_context():
            # Находим записи с проблемными именами файлов
            problematic_records = []
            
            try:
                all_docs = ProductDocument.query.all()
                for doc in all_docs:
                    try:
                        # Пытаемся закодировать имя файла в UTF-8
                        doc.filename.encode('utf-8')
                    except UnicodeEncodeError:
                        problematic_records.append(doc)
                        print(f"Проблемная запись ID {doc.id}: {repr(doc.filename)}")
            except Exception as e:
                print(f"Ошибка при чтении записей: {e}")
                return
            
            if problematic_records:
                print(f"\nНайдено {len(problematic_records)} проблемных записей")
                
                # Удаляем проблемные записи
                for doc in problematic_records:
                    try:
                        print(f"Удаляем запись ID {doc.id}")
                        db.session.delete(doc)
                    except Exception as e:
                        print(f"Ошибка при удалении записи {doc.id}: {e}")
                
                # Сохраняем изменения
                try:
                    db.session.commit()
                    print("Проблемные записи удалены")
                except Exception as e:
                    print(f"Ошибка при сохранении: {e}")
                    db.session.rollback()
            else:
                print("Проблемных записей не найдено")
                
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    clean_problematic_records()
