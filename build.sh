#!/usr/bin/env bash
# exit on error
set -o errexit

# Устанавливаем основные зависимости
pip install -r requirements.txt

# Устанавливаем psycopg2-binary отдельно
pip install psycopg2-binary==2.9.7

# Создаем папку uploads
mkdir -p uploads
