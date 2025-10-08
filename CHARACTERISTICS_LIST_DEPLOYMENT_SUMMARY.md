# Развертывание справочника характеристик (characteristics_list)

## 📋 Что было создано

### 1. Модель базы данных
- **Файл:** `models/characteristics_list.py`
- **Таблица:** `characteristics_list`
- **Поля:**
  - `id` (INTEGER, PRIMARY KEY, AUTO_INCREMENT)
  - `characteristic_key` (VARCHAR(100), UNIQUE, NOT NULL)
  - `unit_of_measurement` (VARCHAR(50), NULLABLE)

### 2. API Routes
- **Файл:** `routes/characteristics_list.py`
- **Endpoints:**
  - `GET /api/characteristics-list` - получить все характеристики
  - `GET /api/characteristics-list/{id}` - получить по ID
  - `POST /api/characteristics-list` - создать (только админы)
  - `PUT /api/characteristics-list/{id}` - обновить (только админы)
  - `DELETE /api/characteristics-list/{id}` - удалить (только админы)

### 3. Скрипты развертывания
- **`create_characteristics_list_table.py`** - создание таблицы
- **`seed_characteristics_list.py`** - заполнение начальными данными
- **`deploy_characteristics_list.py`** - полное развертывание на Render
- **`run_deployment.py`** - запуск развертывания из Procfile

### 4. Документация
- **`CHARACTERISTICS_LIST_API_DOCS.md`** - полная API документация
- **`test_characteristics_api.py`** - скрипт тестирования API

## 🚀 Развертывание на Render

### Автоматическое развертывание
Таблица будет создана автоматически при следующем деплое на Render благодаря обновленному `Procfile`:

```
web: python run_deployment.py && gunicorn app:app --bind 0.0.0.0:$PORT
```

### Ручное развертывание
Если нужно развернуть вручную:

```bash
# На Render сервере
python deploy_characteristics_list.py
```

## 📊 Начальные данные

При развертывании таблица заполняется 20 предопределенными характеристиками:

| ID | Ключ | Единица измерения |
|----|------|-------------------|
| 1 | ВЕС | кг |
| 2 | ДЛИНА | см |
| 3 | ШИРИНА | см |
| 4 | ВЫСОТА | см |
| 5 | ОБЪЕМ | л |
| 6 | МОЩНОСТЬ | Вт |
| 7 | НАПРЯЖЕНИЕ | В |
| 8 | ТОК | А |
| 9 | ЧАСТОТА | Гц |
| 10 | ТЕМПЕРАТУРА | °C |
| 11 | ВЛАЖНОСТЬ | % |
| 12 | ДАВЛЕНИЕ | Па |
| 13 | СКОРОСТЬ | м/с |
| 14 | ВРЕМЯ | сек |
| 15 | РАССТОЯНИЕ | м |
| 16 | ПЛОЩАДЬ | м² |
| 17 | ЦВЕТ | - |
| 18 | МАТЕРИАЛ | - |
| 19 | ПРОИЗВОДИТЕЛЬ | - |
| 20 | МОДЕЛЬ | - |

## 🔧 Интеграция в приложение

### Обновленные файлы:
1. **`models/__init__.py`** - добавлен импорт `CharacteristicsList`
2. **`app.py`** - зарегистрирован blueprint `characteristics_list_bp`

### Новые файлы:
- `models/characteristics_list.py`
- `routes/characteristics_list.py`
- `create_characteristics_list_table.py`
- `seed_characteristics_list.py`
- `deploy_characteristics_list.py`
- `run_deployment.py`
- `test_characteristics_api.py`
- `CHARACTERISTICS_LIST_API_DOCS.md`
- `CHARACTERISTICS_LIST_DEPLOYMENT_SUMMARY.md`

## 🧪 Тестирование

### Локальное тестирование:
```bash
python test_characteristics_api.py
```

### Тестирование на Render:
```bash
curl -X GET "https://pospro-new-server.onrender.com/api/characteristics-list" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 📝 Следующие шаги

1. **Деплой на Render** - таблица создастся автоматически
2. **Тестирование API** - проверка всех endpoints
3. **Интеграция с фронтендом** - использование в UI
4. **Связывание с товарами** - интеграция с существующими характеристиками товаров

## ⚠️ Важные замечания

- Все CRUD операции для характеристик требуют админских прав
- Ключи характеристик должны быть уникальными
- Единицы измерения опциональны
- Таблица создается только при первом развертывании
- При повторном развертывании данные не дублируются
