-- Расширение спец-прав: право настраивать проекты (справочник для задач).
-- Работает так же как can_manage_pipelines для воронок.
--
-- Идемпотентная миграция.

ALTER TABLE system_users
    ADD COLUMN IF NOT EXISTS can_manage_projects BOOLEAN NOT NULL DEFAULT FALSE;
