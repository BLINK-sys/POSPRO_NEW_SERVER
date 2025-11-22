-- Миграция: сделать product_id в таблице order_items nullable
-- Это необходимо для сохранения истории заказов при удалении товаров
-- Дата создания: 2025-11-22

-- Шаг 1: Удаляем NOT NULL constraint с product_id в таблице order_items
ALTER TABLE order_items 
ALTER COLUMN product_id DROP NOT NULL;

-- Проверка: убедиться что изменение применилось
-- SELECT column_name, is_nullable 
-- FROM information_schema.columns 
-- WHERE table_name = 'order_items' AND column_name = 'product_id';
-- Должно показать is_nullable = 'YES'
