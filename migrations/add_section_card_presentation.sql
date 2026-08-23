-- Добавить поле presentation_pdf_url к section_cards — путь к загруженному
-- PDF-файлу презентации. NULL/пусто = презентации нет. Идемпотентно.

ALTER TABLE section_cards
    ADD COLUMN IF NOT EXISTS presentation_pdf_url VARCHAR(512);
