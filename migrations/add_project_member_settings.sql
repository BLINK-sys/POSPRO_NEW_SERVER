-- Таблица per-user настроек видимости задач проекта.
-- Семантика членства в проекте изменилась: «участник» = computed из
-- task.responsible / task.creator / task_member(co-worker|observer).
-- Ручного добавления в project_member больше нет (старая таблица
-- остаётся на месте, не используется, выпилим отдельной миграцией).
--
-- Эта таблица хранит ТОЛЬКО настройку отображения для пары (проект,
-- юзер): видит ли он все задачи проекта или только свои. Запись
-- создаётся лениво при PUT (отсутствие записи = default false).

CREATE TABLE IF NOT EXISTS project_member_settings (
    project_id          INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    user_id             INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    can_see_all_tasks   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_project_member_settings_user
    ON project_member_settings(user_id);
