-- Техническое обслуживание сайта («выключить магазин для всех кроме owner»).
-- Owner в админке создаёт заготовки сообщений (title+body), и когда
-- магазин выключен, одна из заготовок становится «активной табличкой»
-- которую все кроме owner видят на любой странице.

CREATE TABLE IF NOT EXISTS maintenance_notice (
    id         SERIAL PRIMARY KEY,
    title      VARCHAR(255) NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Одна-единственная запись (id=1) с текущим состоянием сайта. Делаем
-- именно таблицу (а не поле в header_settings), чтобы не трогать
-- существующую сущность и чтобы потом проще расширять.
CREATE TABLE IF NOT EXISTS site_mode (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    is_maintenance      BOOLEAN NOT NULL DEFAULT FALSE,
    notice_id           INTEGER REFERENCES maintenance_notice(id) ON DELETE SET NULL,
    started_at          TIMESTAMP,
    started_by_user_id  INTEGER REFERENCES system_users(id) ON DELETE SET NULL,
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT site_mode_singleton CHECK (id = 1)
);

INSERT INTO site_mode (id, is_maintenance) VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;
