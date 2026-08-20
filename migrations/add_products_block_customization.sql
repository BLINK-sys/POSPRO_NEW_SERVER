-- Кастомизация блока товаров на главной: цвет фона карточки-обёртки
-- и переключатель полосы фильтров категорий над списком товаров.
-- Идемпотентно: IF NOT EXISTS через DO $$.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'homepage_blocks' AND column_name = 'background_color'
    ) THEN
        ALTER TABLE homepage_blocks ADD COLUMN background_color VARCHAR(9);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'homepage_blocks' AND column_name = 'show_products_categories_filter'
    ) THEN
        ALTER TABLE homepage_blocks ADD COLUMN show_products_categories_filter BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
END $$;
