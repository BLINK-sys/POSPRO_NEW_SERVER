-- Модуль «Проекты»: контейнер задач с собственным канбаном.
--
-- Расширение Project — статус (active/archived) и владелец.
-- Новая таблица project_member — участники проекта с ролями.
-- Новая таблица project_stage — колонки канбана per-project, каждая
-- мапится на один из 5 глобальных статусов задачи (pending /
-- in_progress / waiting_check / done / paused).
-- Task получает project_stage_id (в какой колонке сейчас) и
-- prev_project_stage_id (куда возвращаться при отмене автомапа).
-- ChatRoom теперь умеет kind='project' + related_project_id.

ALTER TABLE project
    ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES system_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_project_status ON project(status);
CREATE INDEX IF NOT EXISTS ix_project_owner_id ON project(owner_id);

CREATE TABLE IF NOT EXISTS project_member (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    role        VARCHAR(16) NOT NULL DEFAULT 'member',
    added_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_member UNIQUE (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_project_member_project ON project_member(project_id);
CREATE INDEX IF NOT EXISTS ix_project_member_user ON project_member(user_id);

CREATE TABLE IF NOT EXISTS project_stage (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    color           VARCHAR(9) NOT NULL DEFAULT '#94a3b8',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    maps_to_status  VARCHAR(16) NOT NULL DEFAULT 'in_progress',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_project_stage_project ON project_stage(project_id, sort_order);

ALTER TABLE task
    ADD COLUMN IF NOT EXISTS project_stage_id INTEGER
        REFERENCES project_stage(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS prev_project_stage_id INTEGER
        REFERENCES project_stage(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_task_project_stage_id ON task(project_stage_id);

ALTER TABLE chat_room
    ADD COLUMN IF NOT EXISTS related_project_id INTEGER
        REFERENCES project(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_chat_room_related_project ON chat_room(related_project_id);
