-- Удаляем записи с проблемной кодировкой
DELETE FROM product_document WHERE filename ~ '[^\x00-\x7F]';
-- Проверяем результат
SELECT COUNT(*) as total_records FROM product_document;
SELECT id, filename FROM product_document ORDER BY id;