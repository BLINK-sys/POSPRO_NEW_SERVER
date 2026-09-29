-- Миграция: справочник Project + task.project_id + task_checklist.group_name.
--
-- 1) project — новая таблица под верхнеуровневые «проекты» для задач.
--    Название уникально (нельзя два «Маркетинг Q4»). color хранит hex
--    для чипа в таблице задач.
--
-- 2) task.project_id — задача может ссылаться на проект вместо/вместе
--    со сделкой. UI сам выбирает один слот (deal или project).
--
-- 3) task_checklist.group_name — заголовок группы («Астана», «Алматы»).
--    NULL значит без группы, UI покажет их под шапкой «Общее».
--    Группировка вычислимая (SELECT DISTINCT), отдельной таблицы нет.
--
-- Все ALTER'ы идемпотентные (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS project (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL UNIQUE,
    color        VARCHAR(9)  NOT NULL DEFAULT '#facc15',
    description  TEXT NULL,
    created_by   INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_created_by ON project (created_by);

ALTER TABLE task
    ADD COLUMN IF NOT EXISTS project_id INTEGER NULL
    REFERENCES project(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_task_project ON task (project_id);

ALTER TABLE task_checklist
    ADD COLUMN IF NOT EXISTS group_name VARCHAR(120) NULL;

CREATE INDEX IF NOT EXISTS idx_task_checklist_group
    ON task_checklist (task_id, group_name);
