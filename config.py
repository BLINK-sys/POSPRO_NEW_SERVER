import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
    
    # Настройка базы данных для Render
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    # Используем SQLite если PostgreSQL недоступен
    if DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        # SQLite для локальной разработки и fallback
        SQLALCHEMY_DATABASE_URI = "sqlite:///pospro_server.db"
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    JWT_IDENTITY_CLAIM = 'sub'
    
    # Настройка папки загрузок
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), 'uploads'))
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'rar', 'doc', 'docx', 'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'}




