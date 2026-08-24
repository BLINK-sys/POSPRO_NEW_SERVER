-- Добавить поле brands_cards_per_row в homepage_blocks — фикс кол-во
-- карточек в строке для блока брендов. Идемпотентно.

ALTER TABLE homepage_blocks
    ADD COLUMN IF NOT EXISTS brands_cards_per_row INTEGER;
