-- Миграция: два ALTER'а под новый макет карточки сделки.
--
-- 1) deal.creator_id — «Постановщик» (автор сделки). Backfill не делаем:
--    для старых сделок остаётся NULL (их постановщиком считается «система»,
--    UI покажет прочерк). У новых сделок POST /deals заполняет creator_id
--    из JWT-identity.
--
-- 2) entity_attachment.title — человекочитаемый заголовок документа.
--    По дефолту пусто, при первом отображении UI показывает file_name.
--    Идемпотентно (IF NOT EXISTS).

ALTER TABLE deal
    ADD COLUMN IF NOT EXISTS creator_id INTEGER NULL
    REFERENCES system_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_deal_creator
    ON deal (creator_id);

ALTER TABLE entity_attachment
    ADD COLUMN IF NOT EXISTS title VARCHAR(255) NULL;
