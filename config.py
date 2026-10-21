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
    # Render PostgreSQL закрывает idle-соединения через несколько минут.
    # При запуске под gthread (несколько воркер-потоков делят пул)
    # соединение могло «протухнуть» к моменту использования и падать с
    # `SSL SYSCALL error: EOF detected`. Pre-ping делает SELECT 1 перед
    # каждым взятием соединения и поднимает новое если предыдущее мертво.
    # pool_recycle гарантирует что мы заранее переподключимся раньше,
    # чем PostgreSQL нас выкинет (Render обычно идёт 10 минут — ставим 5).
    # Default SQLAlchemy pool_size=5 + max_overflow=10 → 15 коннектов,
    # а у нас 4 worker × 32 thread = 128 потоков. SSE-стримы чата
    # /api/admin/chat/stream держат коннект весь срок подписки (минутами),
    # поэтому pool забивается за секунды и остальные REST-ручки падают с
    # `QueuePool limit of size 5 overflow 10 reached`.
    # 2026-10-21: подняли pool до 20/40 → max 60 коннектов, укладывается
    # в лимит Postgres на Render Standard (~97 connections).
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 20,
        "max_overflow": 40,
        "pool_timeout": 30,
    }
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB (общий лимит; для драйверов проверка 200MB в роуте)
    DRIVER_MAX_SIZE = 200 * 1024 * 1024  # 200MB для драйверов товара
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




