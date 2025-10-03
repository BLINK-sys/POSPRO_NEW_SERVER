# PosPro Shop Backend API

Backend API для интернет-магазина PosPro Shop, построенный на Flask.

## Возможности

- 🔐 Аутентификация пользователей (JWT)
- 📦 Управление товарами и категориями
- 🛒 Корзина и заказы
- ❤️ Избранное
- 🏷️ Бренды и характеристики товаров
- 🎨 Управление баннерами и контентом главной страницы
- 📁 Загрузка файлов (изображения, документы, видео)
- 👥 Управление пользователями (клиенты и админы)

## Технологии

- **Python 3.11+**
- **Flask** - веб-фреймворк
- **Flask-SQLAlchemy** - ORM для работы с базой данных
- **Flask-JWT-Extended** - аутентификация
- **PostgreSQL** - база данных
- **Gunicorn** - WSGI сервер для продакшена

## Установка и запуск

### Локальная разработка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd pospro_new_server
```

2. Создайте виртуальное окружение:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Настройте переменные окружения (опционально):
```bash
# Скопируйте пример файла
cp env.example .env

# Отредактируйте .env файл под свои нужды
# По умолчанию используется локальная PostgreSQL база
```

5. Инициализируйте базу данных:
```bash
python init_db.py
```

6. Запустите сервер:
```bash
# Способ 1: Через скрипт (рекомендуется)
python run_local.py

# Способ 2: Напрямую
python app.py
```

Сервер будет доступен по адресу: `http://localhost:5000`

### Автоматическое определение среды

Проект автоматически определяет среду выполнения:
- **Локально**: 
  - Использует локальную PostgreSQL базу данных
  - Файлы загружаются в папку `./uploads/`
- **На Render**: 
  - Использует PostgreSQL из переменной `DATABASE_URL`
  - Файлы загружаются в `/disk/uploads/` (выделенный диск)

Никаких дополнительных настроек не требуется!

### Развертывание на Render

Проект настроен для автоматического развертывания на Render. Используйте файл `render.yaml` в корне проекта для Blueprint развертывания.

## API Endpoints

### Аутентификация
- `POST /auth/login` - Вход в систему
- `POST /auth/register` - Регистрация
- `GET /auth/me` - Получение информации о текущем пользователе

### Товары
- `GET /products` - Список товаров
- `POST /products` - Создание товара (админ)
- `PUT /products/<id>` - Обновление товара (админ)
- `DELETE /products/<id>` - Удаление товара (админ)

### Категории
- `GET /categories` - Список категорий
- `POST /categories` - Создание категории (админ)

### Корзина
- `GET /api/cart` - Получение корзины
- `POST /api/cart` - Добавление товара в корзину
- `DELETE /api/cart` - Очистка корзины

### Заказы
- `GET /api/orders` - Список заказов пользователя
- `POST /api/orders` - Создание заказа

### Избранное
- `GET /api/favorites` - Список избранного
- `POST /api/favorites` - Добавление в избранное
- `DELETE /api/favorites` - Удаление из избранного

## Структура проекта

```
pospro_new_server/
├── app.py                 # Главный файл приложения
├── config.py             # Конфигурация
├── extensions.py         # Расширения Flask
├── init_db.py           # Инициализация БД
├── requirements.txt     # Зависимости
├── Procfile            # Конфигурация для Render
├── models/             # Модели базы данных
│   ├── __init__.py
│   ├── user.py
│   ├── product.py
│   ├── category.py
│   └── ...
├── routes/             # API маршруты
│   ├── __init__.py
│   ├── auth.py
│   ├── products.py
│   ├── categories.py
│   └── ...
└── utils/              # Утилиты
    └── jwt.py
```

## Переменные окружения

- `SECRET_KEY` - Секретный ключ Flask
- `JWT_SECRET_KEY` - Секретный ключ для JWT
- `DATABASE_URL` - URL подключения к PostgreSQL
- `MAX_CONTENT_LENGTH` - Максимальный размер загружаемых файлов (по умолчанию 20MB)

## Лицензия

MIT License
