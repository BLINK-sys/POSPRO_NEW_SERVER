# API Справочника Характеристик

## Описание
API для работы со справочником характеристик товаров. Позволяет управлять списком доступных характеристик с их единицами измерения.

## Структура данных

### CharacteristicsList
```json
{
  "id": 1,
  "characteristic_key": "ВЕС",
  "unit_of_measurement": "кг"
}
```

**Поля:**
- `id` (int) - Уникальный идентификатор (автоинкремент)
- `characteristic_key` (string) - Ключ характеристики (например, "ВЕС", "ДЛИНА")
- `unit_of_measurement` (string, optional) - Единица измерения (например, "кг", "см")

## API Endpoints

### 1. Получить все характеристики
```
GET /characteristics-list/api/characteristics-list
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
```
GET /characteristics-list/api/characteristics-list/{id}
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
```
POST /characteristics-list/api/characteristics-list
Authorization: Bearer {token}
```

**Тело запроса:**
```json
{
  "characteristic_key": "МОЩНОСТЬ",
  "unit_of_measurement": "Вт"
}
```

**Ответ:**
```json
{
  "success": true,
  "data": {
    "id": 3,
    "characteristic_key": "МОЩНОСТЬ",
    "unit_of_measurement": "Вт"
  },
  "message": "Характеристика создана успешно"
}
```

### 4. Обновить характеристику (только админы)
```
PUT /characteristics-list/api/characteristics-list/{id}
Authorization: Bearer {token}
```

**Тело запроса:**
```json
{
  "characteristic_key": "МОЩНОСТЬ",
  "unit_of_measurement": "кВт"
}
```

**Ответ:**
```json
{
  "success": true,
  "data": {
    "id": 3,
    "characteristic_key": "МОЩНОСТЬ",
    "unit_of_measurement": "кВт"
  },
  "message": "Характеристика обновлена успешно"
}
```

### 5. Удалить характеристику (только админы)
```
DELETE /characteristics-list/api/characteristics-list/{id}
Authorization: Bearer {token}
```

**Ответ:**
```json
{
  "success": true,
  "message": "Характеристика удалена успешно"
}
```

### 6. Поиск характеристик
```
GET /characteristics-list/api/characteristics-list/search?q={query}
```

**Пример:**
```
GET /characteristics-list/api/characteristics-list/search?q=МОЩ
```

**Ответ:**
```json
{
  "success": true,
  "data": [
    {
      "id": 3,
      "characteristic_key": "МОЩНОСТЬ",
      "unit_of_measurement": "Вт"
    }
  ]
}
```

## Коды ошибок

- `400` - Неверные данные запроса
- `401` - Не авторизован
- `403` - Нет прав доступа (только для админов)
- `404` - Характеристика не найдена
- `409` - Конфликт (характеристика с таким ключом уже существует)
- `500` - Внутренняя ошибка сервера

## Предустановленные характеристики

При создании таблицы автоматически добавляются следующие характеристики:

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
| ДАВЛЕНИЕ | Па |
| СКОРОСТЬ | м/с |
| ВРЕМЯ | ч |
| РАЗМЕР | - |
| ЦВЕТ | - |
| МАТЕРИАЛ | - |
| ТИП | - |
| МОДЕЛЬ | - |
| ВЕРСИЯ | - |
| СЕРИЯ | - |

## Использование

### Для фронтенда
```javascript
// Получить все характеристики
const response = await fetch('/characteristics-list/api/characteristics-list');
const data = await response.json();

// Поиск характеристик
const searchResponse = await fetch('/characteristics-list/api/characteristics-list/search?q=ВЕС');
const searchData = await searchResponse.json();
```

### Для админов
```javascript
// Создать новую характеристику
const newChar = await fetch('/characteristics-list/api/characteristics-list', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    characteristic_key: 'НОВАЯ_ХАРАКТЕРИСТИКА',
    unit_of_measurement: 'ед'
  })
});
```
