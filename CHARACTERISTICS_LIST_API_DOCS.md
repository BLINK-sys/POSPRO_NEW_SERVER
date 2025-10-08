# API Документация: Справочник характеристик (characteristics_list)

## Описание
Справочник характеристик содержит предопределенные ключи характеристик с опциональными единицами измерения.

## Структура таблицы
```sql
CREATE TABLE characteristics_list (
    id SERIAL PRIMARY KEY,
    characteristic_key VARCHAR(100) NOT NULL UNIQUE,
    unit_of_measurement VARCHAR(50) NULL
);
```

## API Endpoints

### 1. Получить список всех характеристик
**GET** `/api/characteristics-list`

**Заголовки:**
```
Authorization: Bearer <token>
```

**Ответ:**
```json
{
    "success": true,
    "data": [
        {
            "id": 1,
            "characteristic_key": "ВЕС",
            "unit_of_measurement": "кг"
        },
        {
            "id": 2,
            "characteristic_key": "ДЛИНА",
            "unit_of_measurement": "см"
        }
    ]
}
```

### 2. Получить характеристику по ID
**GET** `/api/characteristics-list/{id}`

**Заголовки:**
```
Authorization: Bearer <token>
```

**Ответ:**
```json
{
    "success": true,
    "data": {
        "id": 1,
        "characteristic_key": "ВЕС",
        "unit_of_measurement": "кг"
    }
}
```

### 3. Создать новую характеристику (только админы)
**POST** `/api/characteristics-list`

**Заголовки:**
```
Authorization: Bearer <admin_token>
Content-Type: application/json
```

**Тело запроса:**
```json
{
    "characteristic_key": "НОВАЯ_ХАРАКТЕРИСТИКА",
    "unit_of_measurement": "ед"
}
```

**Ответ:**
```json
{
    "success": true,
    "message": "Характеристика создана успешно",
    "data": {
        "id": 21,
        "characteristic_key": "НОВАЯ_ХАРАКТЕРИСТИКА",
        "unit_of_measurement": "ед"
    }
}
```

### 4. Обновить характеристику (только админы)
**PUT** `/api/characteristics-list/{id}`

**Заголовки:**
```
Authorization: Bearer <admin_token>
Content-Type: application/json
```

**Тело запроса:**
```json
{
    "characteristic_key": "ОБНОВЛЕННАЯ_ХАРАКТЕРИСТИКА",
    "unit_of_measurement": "новые_единицы"
}
```

**Ответ:**
```json
{
    "success": true,
    "message": "Характеристика обновлена успешно",
    "data": {
        "id": 1,
        "characteristic_key": "ОБНОВЛЕННАЯ_ХАРАКТЕРИСТИКА",
        "unit_of_measurement": "новые_единицы"
    }
}
```

### 5. Удалить характеристику (только админы)
**DELETE** `/api/characteristics-list/{id}`

**Заголовки:**
```
Authorization: Bearer <admin_token>
```

**Ответ:**
```json
{
    "success": true,
    "message": "Характеристика удалена успешно"
}
```

## Начальные данные
При первом развертывании таблица заполняется следующими характеристиками:

| Ключ | Единица измерения |
|------|-------------------|
| ВЕС | кг |
| ДЛИНА | см |
| ШИРИНА | см |
| ВЫСОТА | см |
| ОБЪЕМ | л |
| МОЩНОСТЬ | Вт |
| НАПРЯЖЕНИЕ | В |
| ТОК | А |
| ЧАСТОТА | Гц |
| ТЕМПЕРАТУРА | °C |
| ВЛАЖНОСТЬ | % |
| ДАВЛЕНИЕ | Па |
| СКОРОСТЬ | м/с |
| ВРЕМЯ | сек |
| РАССТОЯНИЕ | м |
| ПЛОЩАДЬ | м² |
| ЦВЕТ | - |
| МАТЕРИАЛ | - |
| ПРОИЗВОДИТЕЛЬ | - |
| МОДЕЛЬ | - |

## Коды ошибок
- **400** - Неверные данные запроса
- **401** - Не авторизован
- **403** - Недостаточно прав (только для админов)
- **404** - Характеристика не найдена
- **500** - Внутренняя ошибка сервера

## Примеры использования

### Получить все характеристики
```bash
curl -X GET "https://pospro-new-server.onrender.com/api/characteristics-list" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Создать новую характеристику
```bash
curl -X POST "https://pospro-new-server.onrender.com/api/characteristics-list" \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "characteristic_key": "РАЗМЕР",
    "unit_of_measurement": "мм"
  }'
```
