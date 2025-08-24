#!/usr/bin/env bash
# exit on error
set -o errexit

# Создаем папку uploads если её нет
mkdir -p uploads

# Запускаем приложение с gunicorn
gunicorn app:app --bind 0.0.0.0:$PORT
