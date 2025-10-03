import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")

    # Проверяем, что DATABASE_URL задан
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("❌ DATABASE_URL is not set in environment variables!")

    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    JWT_IDENTITY_CLAIM = 'sub'

    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB

    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'rar', 'doc', 'docx',
        'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm'
    }
