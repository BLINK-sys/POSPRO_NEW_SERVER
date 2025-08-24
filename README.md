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

### Локальная разработка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/BLINK-sys/POSPRO_NEW_SERVER.git
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
DATABASE_URL=postgresql://pospro:yfcnhjqrf@localhost:5432/pospro_server_db
JWT_SECRET_KEY=your-jwt-secret-key
```

6. Запустите сервер:
```bash
python app.py
```

### Деплой на Render

1. **Создайте аккаунт на Render:**
   - Перейдите на https://render.com
   - Зарегистрируйтесь или войдите в аккаунт

2. **Подключите GitHub репозиторий:**
   - Нажмите "New +" → "Web Service"
   - Подключите ваш GitHub аккаунт
   - Выберите репозиторий `POSPRO_NEW_SERVER`

3. **Настройте Web Service:**
   - **Name:** `pospro-shop-server`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Plan:** Free

4. **Создайте базу данных PostgreSQL:**
   - Нажмите "New +" → "PostgreSQL"
   - **Name:** `pospro-shop-db`
   - **Database:** `pospro_server_db`
   - **User:** `pospro_user`
   - **Plan:** Free

5. **Настройте переменные окружения:**
   - В настройках Web Service добавьте:
     - `DATABASE_URL` = Connection String из PostgreSQL
     - `SECRET_KEY` = сгенерированный секретный ключ
     - `JWT_SECRET_KEY` = сгенерированный JWT секретный ключ

6. **Деплой:**
   - Нажмите "Create Web Service"
   - Render автоматически развернет ваше приложение

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
