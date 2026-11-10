-- История сохранений attachment'а: каждый PUT /raw из встроенного
-- редактора создаёт снимок старого содержимого файла. Лимит 30 версий
-- на attachment (старые удаляются бизнес-логикой на бэке вместе с
-- файлом на диске).
--
-- FK с ON DELETE CASCADE: при удалении attachment запись версии уйдёт
-- автоматически из БД. Файлы на диске чистятся из роута delete_attachment.

CREATE TABLE IF NOT EXISTS entity_attachment_version (
    id              SERIAL PRIMARY KEY,
    attachment_id   INTEGER NOT NULL REFERENCES entity_attachment(id) ON DELETE CASCADE,
    disk_path       VARCHAR(1024) NOT NULL,
    file_size       BIGINT,
    saved_by        INTEGER REFERENCES system_users(id) ON DELETE SET NULL,
    saved_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_eav_attachment ON entity_attachment_version(attachment_id);
CREATE INDEX IF NOT EXISTS ix_eav_saved_at ON entity_attachment_version(saved_at);
