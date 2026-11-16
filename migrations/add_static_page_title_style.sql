-- Оформление H1-заголовка статической страницы:
--   title_color  — hex color (без влияния на <title> и метаданные)
--   title_align  — left | center | right
--   title_hidden — не рендерить H1 на странице (title вкладки остаётся)

ALTER TABLE static_pages
    ADD COLUMN IF NOT EXISTS title_color  VARCHAR(16),
    ADD COLUMN IF NOT EXISTS title_align  VARCHAR(16) NOT NULL DEFAULT 'left',
    ADD COLUMN IF NOT EXISTS title_hidden BOOLEAN NOT NULL DEFAULT false;
