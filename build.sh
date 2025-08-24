#!/usr/bin/env bash
# exit on error
set -o errexit

# Устанавливаем системные зависимости PostgreSQL
apt-get update && apt-get install -y libpq-dev postgresql-client build-essential

# Устанавливаем основные Python зависимости
pip install Flask==2.3.3 Flask-CORS==4.0.0 Flask-JWT-Extended==4.5.3 Flask-SQLAlchemy==3.0.5 gunicorn==21.2.0 python-dotenv==1.0.0

# Устанавливаем PostgreSQL драйвер (продолжаем даже при ошибках)
python install_postgresql.py || echo "⚠️ Предупреждение: Не все драйверы установились, но продолжаем..."

# Создаем папку uploads
mkdir -p uploads

# Инициализируем базу данных
python init_db.py
