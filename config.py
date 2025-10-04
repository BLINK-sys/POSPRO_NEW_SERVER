import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла (только для локальной разработки)
if not os.getenv("RENDER"):  # Не загружаем .env на Render
    load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    JWT_IDENTITY_CLAIM = 'sub'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'rar', 'doc', 'docx',
        'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'
    }

    # Определяем среду выполнения и настраиваем базу данных и пути загрузки
    if os.getenv("RENDER"):  # Render автоматически устанавливает эту переменную
        print("Render configuration...")
        # Проверяем, что DATABASE_URL задан
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set in environment variables!")
        SQLALCHEMY_DATABASE_URI = db_url
        
        # На Render используем /disk/uploads для постоянного хранения
        UPLOAD_FOLDER = "/disk/uploads"
        print("Render config loaded successfully")
    else:
        print("Local development configuration...")
        # Локальная база данных PostgreSQL
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://pospro:yfcnhjqrf@localhost:5432/pospro_server_db")
        
        # Локально используем папку uploads рядом с приложением
        UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
        print("Local config loaded successfully")




