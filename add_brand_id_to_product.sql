-- Добавить колонку brand_id в таблицу product
-- Для PostgreSQL
ALTER TABLE product ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brand(id);

-- Обновить существующие записи: найти brand_id по названию бренда
-- Это нужно сделать после добавления колонки
UPDATE product 
SET brand_id = (
    SELECT id FROM brand 
    WHERE brand.name = product.brand 
    LIMIT 1
)
WHERE product.brand IS NOT NULL 
  AND product.brand != '' 
  AND product.brand_id IS NULL;

-- Для SQLite (если используется)
-- ALTER TABLE product ADD COLUMN brand_id INTEGER REFERENCES brand(id);
-- UPDATE product 
-- SET brand_id = (
--     SELECT id FROM brand 
--     WHERE brand.name = product.brand 
--     LIMIT 1
-- )
-- WHERE product.brand IS NOT NULL 
--   AND product.brand != '' 
--   AND product.brand_id IS NULL;

