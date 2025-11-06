-- Миграция: перенос данных из колонки brand в brand_id и удаление колонки brand
-- 
-- ШАГ 1: Добавить колонку brand_id (если еще не добавлена)
-- ALTER TABLE product ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brand(id);

-- ШАГ 2: Заполнить brand_id для существующих товаров на основе названия бренда
-- UPDATE product 
-- SET brand_id = (
--     SELECT id FROM brand 
--     WHERE brand.name = product.brand 
--     LIMIT 1
-- )
-- WHERE product.brand IS NOT NULL 
--   AND product.brand != '' 
--   AND product.brand_id IS NULL;

-- ШАГ 3: После успешной миграции всех данных, удалить колонку brand
-- Для PostgreSQL:
-- ALTER TABLE product DROP COLUMN IF EXISTS brand;

-- Для SQLite (не поддерживает DROP COLUMN напрямую):
-- Нужно пересоздать таблицу без колонки brand

