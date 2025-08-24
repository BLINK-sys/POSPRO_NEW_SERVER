#!/usr/bin/env bash
# exit on error
set -o errexit

# Устанавливаем системные зависимости PostgreSQL
apt-get update && apt-get install -y libpq-dev postgresql-client

# Устанавливаем Python зависимости
pip install -r requirements.txt

# Создаем папку uploads
mkdir -p uploads

# Инициализируем базу данных
python init_db.py
