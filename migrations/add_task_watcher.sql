-- Избранные (отслеживаемые) задачи — per-user список.
-- Пользователь жмёт звёздочку на задаче, она попадает в его личный
-- список «Отслеживаемые». Отдельного sync с ролью нет: подписка
-- пользовательская, не производная от responsible/creator/member.
-- См. models.task.TaskWatcher.

CREATE TABLE IF NOT EXISTS task_watcher (
    user_id    INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    task_id    INTEGER NOT NULL REFERENCES task(id)         ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, task_id)
);

CREATE INDEX IF NOT EXISTS ix_task_watcher_user ON task_watcher(user_id);
CREATE INDEX IF NOT EXISTS ix_task_watcher_task ON task_watcher(task_id);
