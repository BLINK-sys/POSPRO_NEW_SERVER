import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
    
    # Настройка базы данных PostgreSQL для Render с psycopg v3
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    
    # Fallback на локальную базу если DATABASE_URL не установлен
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or "postgresql+psycopg://pospro_user:mAbPOToSmG4Cc9o0v6fw8WA2gvQZyOAT@dpg-d2ld55ripnbc7383bnig-a.frankfurt-postgres.render.com/pospro_server_db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    JWT_IDENTITY_CLAIM = 'sub'
    
    # Настройка папки загрузок - используем /var/data/uploads на Render
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/var/data/uploads")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'rar', 'doc', 'docx', 'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'}




