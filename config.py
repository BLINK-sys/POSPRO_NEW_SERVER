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
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'rar', 'doc', 'docx',
        'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'
    }

    # Определяем среду выполнения
    def __init__(self):
        # Проверяем, работаем ли мы на Render
        if os.getenv("RENDER"):  # Render автоматически устанавливает эту переменную
            self._setup_render_config()
        else:
            self._setup_local_config()

    def _setup_render_config(self):
        """Конфигурация для Render"""
        print("Render configuration...")
        
        # Проверяем, что DATABASE_URL задан
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set in environment variables!")
        
        self.SQLALCHEMY_DATABASE_URI = db_url
        print("Render config loaded successfully")

    def _setup_local_config(self):
        """Конфигурация для локальной разработки"""
        print("Local development configuration...")
        
        # Локальная база данных SQLite
        self.SQLALCHEMY_DATABASE_URI = "sqlite:///pospro.db"
        print("Local config loaded successfully")
