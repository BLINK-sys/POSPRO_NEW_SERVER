#!/usr/bin/env python3
"""
Миграция структуры файлов для баннеров и малых баннеров
"""

import os
import shutil
from flask import Flask
from extensions import db
from models.banner import Banner
from models.small_banner_card import SmallBanner

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://pospro:your_password@localhost/pospro_server_db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def migrate_banner_files():
    """Миграция файлов баннеров в структуру по ID"""
    app = create_app()
    
    with app.app_context():
        print("🔄 Начинаем миграцию файлов баннеров...")
        
        # Получаем все баннеры
        banners = Banner.query.all()
        
        for banner in banners:
            if banner.image and banner.image.startswith('/uploads/banners/'):
                # Извлекаем имя файла из старого пути
                old_filename = banner.image.replace('/uploads/banners/', '')
                old_path = os.path.join('uploads', 'banners', old_filename)
                
                if os.path.exists(old_path):
                    # Создаем новую директорию для баннера
                    new_dir = os.path.join('uploads', 'banners', str(banner.id))
                    os.makedirs(new_dir, exist_ok=True)
                    
                    # Перемещаем файл
                    new_path = os.path.join(new_dir, old_filename)
                    shutil.move(old_path, new_path)
                    
                    # Обновляем путь в базе данных
                    banner.image = f'/uploads/banners/{banner.id}/{old_filename}'
                    
                    print(f"✅ Баннер {banner.id}: {old_path} → {new_path}")
                else:
                    print(f"⚠️  Файл не найден: {old_path}")
        
        db.session.commit()
        print("✅ Миграция баннеров завершена")

def migrate_small_banner_files():
    """Миграция файлов малых баннеров в структуру по ID"""
    app = create_app()
    
    with app.app_context():
        print("🔄 Начинаем миграцию файлов малых баннеров...")
        
        # Получаем все малые баннеры
        small_banners = SmallBanner.query.all()
        
        for banner in small_banners:
            # Миграция основного изображения
            if banner.image_url and banner.image_url.startswith('/uploads/small_banners/'):
                old_filename = banner.image_url.replace('/uploads/small_banners/', '')
                old_path = os.path.join('uploads', 'small_banners', old_filename)
                
                if os.path.exists(old_path):
                    # Создаем новую директорию
                    new_dir = os.path.join('uploads', 'banners', 'small_banners', str(banner.id))
                    os.makedirs(new_dir, exist_ok=True)
                    
                    # Перемещаем файл
                    new_path = os.path.join(new_dir, old_filename)
                    shutil.move(old_path, new_path)
                    
                    # Обновляем путь в базе данных
                    banner.image_url = f'/uploads/banners/small_banners/{banner.id}/{old_filename}'
                    
                    print(f"✅ Малый баннер {banner.id} (image): {old_path} → {new_path}")
                else:
                    print(f"⚠️  Файл не найден: {old_path}")
            
            # Миграция фонового изображения
            if banner.background_image_url and banner.background_image_url.startswith('/uploads/small_banners/'):
                old_filename = banner.background_image_url.replace('/uploads/small_banners/', '')
                old_path = os.path.join('uploads', 'small_banners', old_filename)
                
                if os.path.exists(old_path):
                    # Создаем новую директорию
                    new_dir = os.path.join('uploads', 'banners', 'small_banners', str(banner.id))
                    os.makedirs(new_dir, exist_ok=True)
                    
                    # Перемещаем файл
                    new_path = os.path.join(new_dir, old_filename)
                    shutil.move(old_path, new_path)
                    
                    # Обновляем путь в базе данных
                    banner.background_image_url = f'/uploads/banners/small_banners/{banner.id}/{old_filename}'
                    
                    print(f"✅ Малый баннер {banner.id} (background): {old_path} → {new_path}")
                else:
                    print(f"⚠️  Файл не найден: {old_path}")
        
        db.session.commit()
        print("✅ Миграция малых баннеров завершена")

def cleanup_empty_directories():
    """Удаление пустых директорий после миграции"""
    print("🧹 Удаляем пустые директории...")
    
    directories_to_check = [
        'uploads/small_banners',
        'uploads/banners'  # Проверяем только если в ней нет подпапок
    ]
    
    for directory in directories_to_check:
        if os.path.exists(directory):
            try:
                # Проверяем, пуста ли директория
                if not os.listdir(directory):
                    os.rmdir(directory)
                    print(f"🗑️  Удалена пустая директория: {directory}")
                else:
                    print(f"📁 Директория не пуста, оставляем: {directory}")
            except Exception as e:
                print(f"⚠️  Ошибка при удалении {directory}: {e}")

if __name__ == "__main__":
    migrate_banner_files()
    migrate_small_banner_files()
    cleanup_empty_directories()
    print("🎉 Миграция завершена!")
