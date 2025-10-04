-- Скрипт для исправления кодировки имен файлов в PostgreSQL

-- Проверяем текущую кодировку базы данных
SELECT datname, datcollate, datctype 
FROM pg_database 
WHERE datname = current_database();

-- Проверяем записи с проблемными именами файлов
SELECT id, filename, encode(filename::bytea, 'hex') as filename_hex
FROM product_document 
WHERE filename ~ '[^\x00-\x7F]'
ORDER BY id;

-- Обновляем кодировку для проблемных записей
-- Попробуем исправить через конвертацию из latin1 в utf8
UPDATE product_document 
SET filename = convert_from(convert_to(filename, 'latin1'), 'utf8')
WHERE filename ~ '[^\x00-\x7F]'
AND convert_from(convert_to(filename, 'latin1'), 'utf8') != filename;

-- Альтернативный способ - через cp1251
UPDATE product_document 
SET filename = convert_from(convert_to(filename, 'windows-1251'), 'utf8')
WHERE filename ~ '[^\x00-\x7F]'
AND convert_from(convert_to(filename, 'windows-1251'), 'utf8') != filename;

-- Проверяем результат
SELECT id, filename 
FROM product_document 
ORDER BY id;
