-- Справочники для «опросника при переходе стадии» (Теплота, Город,
-- Вид деятельности, Тип бизнеса — изначально. Админ может добавить
-- любые новые). Устройство: родительская `dictionary` (code+label) и
-- дочерние `dictionary_item` (name/order/is_active).
--
-- Связь со стадией: deal_stage.required_dict_codes JSONB — массив
-- кодов справочников, обязательных на ВХОДЕ в стадию. Проверка в
-- POST /deals/<id>/move — если какие-то пусты → 400 с missing_codes,
-- фронт показывает модалку.
--
-- Значения на сделке: deal.survey_values JSONB — объект вида
-- dict_code → dict_item_id. Отображаются в блоке Информация карточки сделки.
--
-- Источники (DealSource) оставлены отдельной таблицей — у них своя
-- 2-уровневая структура (parent + variant).

CREATE TABLE IF NOT EXISTS dictionary (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(64) NOT NULL UNIQUE,
    label       VARCHAR(255) NOT NULL,
    order_pos   INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dictionary_item (
    id          SERIAL PRIMARY KEY,
    dict_id     INTEGER NOT NULL REFERENCES dictionary(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    order_pos   INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dict_item UNIQUE (dict_id, name)
);

CREATE INDEX IF NOT EXISTS ix_dict_item_dict ON dictionary_item(dict_id);

ALTER TABLE deal_stage
    ADD COLUMN IF NOT EXISTS required_dict_codes JSONB
    NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE deal
    ADD COLUMN IF NOT EXISTS survey_values JSONB
    NOT NULL DEFAULT '{}'::jsonb;
