# 📸 API загрузки изображений и видео товаров

## 🔧 Исправления

### ✅ Проблема решена
- **Раньше:** Файлы загружались на диск, но URL не записывался в базу данных
- **Теперь:** После загрузки файла автоматически создается запись в таблице `ProductMedia`

## 🚀 API Endpoints

### 1. Загрузка медиафайлов товара

#### `POST /upload/upload_product`
**Основной эндпоинт для загрузки изображений и видео**

**Параметры:**
- `file` - файл для загрузки (обязательно)
- `product_id` - ID товара (обязательно)

**Поддерживаемые форматы:**
- **Изображения:** PNG, JPG, JPEG, GIF
- **Видео:** MP4, MOV, AVI, MKV, WMV, FLV, WEBM

**Пример запроса:**
```bash
curl -X POST http://localhost:5000/upload/upload_product \
  -F "file=@image.jpg" \
  -F "product_id=1"
```

**Ответ:**
```json
{
  "message": "File uploaded and saved to database",
  "url": "/uploads/products/1/image.jpg",
  "id": 123,
  "media_type": "image",
  "filename": "image.jpg"
}
```

#### `POST /upload/upload_product_image`
**Альтернативный эндпоинт для изображений** (тот же функционал)

#### `POST /upload/upload_product_video`
**Альтернативный эндпоинт для видео** (тот же функционал)

### 2. Получение медиафайлов товара

#### `GET /upload/media/{product_id}`
**Получение всех медиафайлов товара**

**Пример запроса:**
```bash
curl http://localhost:5000/upload/media/1
```

**Ответ:**
```json
[
  {
    "id": 123,
    "url": "/uploads/products/1/image.jpg",
    "media_type": "image",
    "order": 0
  },
  {
    "id": 124,
    "url": "/uploads/products/1/video.mp4",
    "media_type": "video",
    "order": 1
  }
]
```

### 3. Добавление медиа по URL

#### `POST /upload/media/{product_id}`
**Добавление медиафайла по URL (для внешних ссылок)**

**Параметры (JSON):**
```json
{
  "url": "https://example.com/image.jpg",
  "media_type": "image"
}
```

### 4. Удаление медиафайла

#### `DELETE /upload/media/{media_id}`
**Удаление медиафайла и файла с диска**

### 5. Изменение порядка медиафайлов

#### `POST /upload/media/reorder/{product_id}`
**Изменение порядка отображения медиафайлов**

**Параметры (JSON):**
```json
[
  {"id": 123, "order": 0},
  {"id": 124, "order": 1}
]
```

## 🔄 Автоматическая синхронизация

### Функция `sync_media_from_filesystem(product_id)`
- Автоматически вызывается при получении медиафайлов
- Создает записи в БД для файлов, которые есть на диске, но отсутствуют в БД
- Определяет тип медиа на основе расширения файла

## 🗄️ Структура базы данных

### Таблица `ProductMedia`
```sql
CREATE TABLE product_media (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    url VARCHAR(500) NOT NULL,
    media_type VARCHAR(10) NOT NULL,  -- 'image' или 'video'
    order INTEGER DEFAULT 0
);
```

## 📁 Структура файловой системы

```
uploads/
└── products/
    └── {product_id}/
        ├── image1.jpg
        ├── image2.png
        ├── video1.mp4
        ├── documents/
        │   └── document1.pdf
        └── drivers/
            └── driver1.zip
```

## 🛡️ Безопасность

### Валидация файлов
- Проверка расширения файла
- Максимальный размер: 20MB
- Санитизация имен файлов (поддержка русских символов)

### Обработка ошибок
- Если не удается записать в БД, файл удаляется с диска
- Логирование ошибок
- Откат транзакций при ошибках

## 🧪 Тестирование

Запустите тестовый скрипт:
```bash
python test_upload.py
```

## 📝 Примеры использования

### JavaScript (Frontend)
```javascript
// Загрузка изображения
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('product_id', '1');

fetch('/upload/upload_product', {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => {
  console.log('Файл загружен:', data);
});

// Получение медиафайлов
fetch('/upload/media/1')
.then(response => response.json())
.then(media => {
  console.log('Медиафайлы:', media);
});
```

### Python (Backend)
```python
import requests

# Загрузка файла
with open('image.jpg', 'rb') as f:
    files = {'file': ('image.jpg', f, 'image/jpeg')}
    data = {'product_id': '1'}
    
    response = requests.post('http://localhost:5000/upload/upload_product', 
                           files=files, data=data)
    print(response.json())

# Получение медиафайлов
response = requests.get('http://localhost:5000/upload/media/1')
media_files = response.json()
print(media_files)
```

## ✅ Что исправлено

1. **Автоматическая запись в БД** - после загрузки файла создается запись в `ProductMedia`
2. **Определение типа медиа** - автоматически по расширению файла
3. **Синхронизация файловой системы** - автоматическое создание записей для существующих файлов
4. **Обработка ошибок** - удаление файла при неудачной записи в БД
5. **Расширенные форматы** - добавлена поддержка видео файлов
6. **Улучшенные ответы** - больше информации в JSON ответах 