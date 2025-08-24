# POSPRO Shop Server

Backend сервер для интернет-магазина POSPRO Shop, построенный на Flask.

## Описание

Этот проект представляет собой REST API сервер для управления интернет-магазином, включающий функциональность для работы с товарами, категориями, заказами, пользователями и другими компонентами e-commerce системы.

## Технологии

- **Python 3.11+**
- **Flask** - веб-фреймворк
- **SQLAlchemy** - ORM для работы с базой данных
- **Flask-JWT-Extended** - аутентификация и авторизация
- **Flask-CORS** - поддержка CORS

## Установка и запуск

1. Клонируйте репозиторий:
```bash
git clone https://github.com/your-username/POSPRO_NEW_SERVER.git
cd POSPRO_NEW_SERVER
```

2. Создайте виртуальное окружение:
```bash
python -m venv venv
```

3. Активируйте виртуальное окружение:
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

4. Установите зависимости:
```bash
pip install -r requirements.txt
```

5. Настройте переменные окружения (создайте файл .env):
```env
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=your-secret-key
DATABASE_URL=your-database-url
```

6. Запустите сервер:
```bash
python app.py
```

## Структура проекта

```
POSPRO_NEW_SERVER/
├── app.py                 # Главный файл приложения
├── config.py             # Конфигурация
├── extensions.py         # Расширения Flask
├── requirements.txt      # Зависимости
├── models/              # Модели данных
├── routes/              # API маршруты
├── utils/               # Утилиты
└── uploads/             # Загруженные файлы
```

## API Endpoints

### Аутентификация
- `POST /auth/login` - Вход в систему
- `POST /auth/register` - Регистрация

### Товары
- `GET /products` - Получить список товаров
- `POST /products` - Создать товар
- `GET /products/<id>` - Получить товар по ID
- `PUT /products/<id>` - Обновить товар
- `DELETE /products/<id>` - Удалить товар

### Категории
- `GET /categories` - Получить список категорий
- `POST /categories` - Создать категорию

### Заказы
- `GET /orders` - Получить список заказов
- `POST /orders` - Создать заказ
- `GET /orders/<id>` - Получить заказ по ID

### Корзина
- `GET /cart` - Получить корзину пользователя
- `POST /cart/add` - Добавить товар в корзину
- `DELETE /cart/remove/<id>` - Удалить товар из корзины

## Лицензия

MIT License
