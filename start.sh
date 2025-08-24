#!/usr/bin/env bash
# exit on error
set -o errexit

# Создаем папку uploads если её нет
mkdir -p uploads

# Запускаем приложение
python app.py
