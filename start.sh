#!/usr/bin/env bash
set -e

# Создаем папку uploads если её нет
mkdir -p uploads

# Инициализируем базу данных
python init_db.py

# Запускаем приложение
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2
