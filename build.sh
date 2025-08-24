#!/usr/bin/env bash
# exit on error
set -o errexit

# Устанавливаем зависимости
pip install -r requirements.txt

# Создаем папку uploads
mkdir -p uploads

# Инициализируем базу данных
python init_db.py
