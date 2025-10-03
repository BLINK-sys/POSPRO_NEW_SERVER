# API Документация: Избранное

## Обзор

Функциональность избранного позволяет клиентам добавлять товары в свой список избранных для быстрого доступа в дальнейшем.

## Модель данных

### Таблица `favorites`

```sql
CREATE TABLE favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES product(id),
    UNIQUE(user_id, product_id)
);
```

## API Эндпоинты

Все эндпоинты требуют авторизации с JWT токеном в заголовке `Authorization: Bearer <token>`.

### 1. Получить список избранного

**GET** `/api/favorites`

**Ответ:**
```json
{
  "success": true,
  "favorites": [
    {
      "id": 1,
      "user_id": 123,
      "product_id": 456,
      "created_at": "2024-01-15T10:30:00",
      "product": {
        "id": 456,
        "name": "Название товара",
        "slug": "tovar-slug",
        "price": 15000,
        "article": "ART123",
        "image_url": "/uploads/products/456/image.jpg",
        "status": {
          "id": 1,
          "name": "В наличии",
          "background_color": "#22c55e",
          "text_color": "#ffffff"
        },
        "category": {
          "id": 10,
          "name": "Категория товара",
          "slug": "category-slug"
        }
      }
    }
  ],
  "count": 1
}
```

### 2. Добавить товар в избранное

**POST** `/api/favorites`

**Тело запроса:**
```json
{
  "product_id": 456
}
```

**Ответ:**
```json
{
  "success": true,
  "message": "Товар добавлен в избранное",
  "favorite": {
    "id": 1,
    "user_id": 123,
    "product_id": 456,
    "created_at": "2024-01-15T10:30:00",
    "product": { /* объект товара */ }
  }
}
```

### 3. Удалить товар из избранного

**DELETE** `/api/favorites/{product_id}`

**Ответ:**
```json
{
  "success": true,
  "message": "Товар удален из избранного"
}
```

### 4. Проверить статус избранного

**GET** `/api/favorites/check/{product_id}`

**Ответ:**
```json
{
  "success": true,
  "is_favorite": true
}
```

### 5. Переключить статус избранного

**POST** `/api/favorites/toggle`

**Тело запроса:**
```json
{
  "product_id": 456
}
```

**Ответ (добавление):**
```json
{
  "success": true,
  "message": "Товар добавлен в избранное",
  "is_favorite": true,
  "favorite": { /* объект избранного */ }
}
```

**Ответ (удаление):**
```json
{
  "success": true,
  "message": "Товар удален из избранного",
  "is_favorite": false
}
```

## Коды ошибок

| Код | Описание |
|-----|----------|
| 400 | Неверные данные запроса |
| 401 | Требуется авторизация |
| 404 | Товар не найден или не в избранном |
| 409 | Товар уже в избранном |
| 500 | Внутренняя ошибка сервера |

## Примеры использования

### JavaScript/TypeScript

```typescript
// Добавить в избранное
const addToFavorites = async (productId: number) => {
  const response = await fetch('/api/favorites', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ product_id: productId })
  });
  
  return await response.json();
};

// Получить список избранного
const getFavorites = async () => {
  const response = await fetch('/api/favorites', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  return await response.json();
};

// Переключить статус
const toggleFavorite = async (productId: number) => {
  const response = await fetch('/api/favorites/toggle', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ product_id: productId })
  });
  
  return await response.json();
};
```

## Установка и миграция

1. Убедитесь, что модель `Favorite` импортирована в `models/__init__.py`
2. Запустите скрипт создания таблицы:
```bash
python create_favorites_table.py
```

## Frontend компоненты

### FavoriteButton
Универсальная кнопка для переключения статуса избранного:

```tsx
<FavoriteButton
  productId={product.id}
  productName={product.name}
  className="w-8 h-8"
  size="sm"
  showText={false}
/>
```

### FavoritesGrid
Компонент для отображения сетки избранных товаров на странице профиля:

```tsx
<FavoritesGrid favorites={favorites} />
```

## Особенности

1. **Уникальность**: Один товар может быть добавлен в избранное только один раз
2. **Авторизация**: Функция доступна только авторизованным клиентам
3. **Роли**: Избранное доступно только пользователям с ролью "client"
4. **Автоочистка**: При удалении товара или пользователя, связанные записи в избранном удаляются автоматически
5. **Производительность**: Используется eager loading для связанных объектов

## Безопасность

- Все эндпоинты защищены JWT авторизацией
- Пользователи могут управлять только своим избранным
- Валидация данных на стороне сервера
- Защита от SQL инъекций через ORM
