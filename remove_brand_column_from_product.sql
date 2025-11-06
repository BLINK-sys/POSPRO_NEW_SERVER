-- Удалить колонку brand из таблицы product
-- ВАЖНО: Сначала нужно выполнить миграцию для добавления brand_id и заполнения данных
-- Затем можно удалить колонку brand

-- Для PostgreSQL
ALTER TABLE product DROP COLUMN IF EXISTS brand;

-- Для SQLite (не поддерживает DROP COLUMN напрямую, нужна пересоздание таблицы)
-- В SQLite нужно пересоздать таблицу без колонки brand

