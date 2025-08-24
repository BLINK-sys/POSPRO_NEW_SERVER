#!/usr/bin/env bash
# exit on error
set -o errexit

# Устанавливаем основные зависимости
pip install Flask==3.0.0 Flask-CORS==4.0.0 Flask-JWT-Extended==4.6.0 Flask-SQLAlchemy==3.1.1 gunicorn==21.2.0 python-dotenv==1.0.0

# Устанавливаем PostgreSQL драйвер
python install_deps.py

# Создаем папку uploads
mkdir -p uploads
