-- Таблица customer_activity_events — единый event-log действий покупателей
-- (не admin/system). Идемпотентно.

CREATE TABLE IF NOT EXISTS customer_activity_events (
    id             SERIAL PRIMARY KEY,
    event_type     VARCHAR(32) NOT NULL,
    user_id        INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
    ip_address     VARCHAR(45),
    user_agent     TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    search_query   VARCHAR(500),
    results_count  INTEGER,
    category_id    INTEGER REFERENCES category(id) ON DELETE SET NULL,
    category_name  VARCHAR(255),
    category_slug  VARCHAR(255),
    brand_id       INTEGER REFERENCES brand(id)   ON DELETE SET NULL,
    brand_name     VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_customer_activity_type_date
    ON customer_activity_events (event_type, created_at);

CREATE INDEX IF NOT EXISTS idx_customer_activity_query
    ON customer_activity_events (search_query);

CREATE INDEX IF NOT EXISTS idx_customer_activity_category
    ON customer_activity_events (category_id);

CREATE INDEX IF NOT EXISTS idx_customer_activity_brand
    ON customer_activity_events (brand_id);
