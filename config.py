import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
    # Используем переменную окружения для URL базы данных (для Render)
    #SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://pospro:yfcnhjqrf@localhost:5432/pospro_server_db")    
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://pospro_user:FkfSdSLXtK9ZFei3tch3KmUYuLOeq1rO@dpg-d3fnijili9vc73e7pvq0-a/pospro_db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    JWT_IDENTITY_CLAIM = 'sub'
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'rar', 'doc', 'docx', 'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'}




