-- Добавляем поля для цветов текста в таблицу small_banners
ALTER TABLE small_banners 
ADD COLUMN title_text_color VARCHAR(7) DEFAULT '#000000',
ADD COLUMN description_text_color VARCHAR(7) DEFAULT '#666666';

-- Комментарии для полей
COMMENT ON COLUMN small_banners.title_text_color IS 'Цвет текста заголовка в формате HEX';
COMMENT ON COLUMN small_banners.description_text_color IS 'Цвет текста описания в формате HEX';
