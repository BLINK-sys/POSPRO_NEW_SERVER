#!/usr/bin/env bash
set -e

# Создаем папку uploads в /var/data если её нет
mkdir -p /var/data/uploads

# Выводим информацию о подключении к БД
echo "🗄️ Подключение к базе данных..."
echo "DATABASE_URL: $DATABASE_URL"

# Инициализируем базу данных с повторными попытками
echo "🔧 Инициализация базы данных..."
for i in {1..3}; do
    echo "Попытка $i из 3..."
    if python init_db.py; then
        echo "✅ База данных инициализирована успешно!"
        break
    else
        echo "❌ Ошибка при инициализации БД (попытка $i)"
        if [ $i -eq 3 ]; then
            echo "💥 Все попытки инициализации БД провалились!"
            exit 1
        fi
        sleep 5
    fi
done

# Запускаем приложение
echo "🚀 Запуск приложения..."
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2
