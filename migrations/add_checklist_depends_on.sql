-- Миграция: task_checklist.depends_on_group.
--
-- Позволяет объявить зависимость одной группы чек-листа от другой:
-- пока «предыдущая» группа не завершена на 100 процентов, «зависимая»
-- группа блокируется в UI (пункты нельзя отмечать). Значение —
-- имя (group_name) блокирующей группы в той же задаче. NULL значит
-- независимо. Валидация ссылки — на уровне приложения, foreign key
-- на строку group_name не завести.
--
-- Идемпотентно.

ALTER TABLE task_checklist
    ADD COLUMN IF NOT EXISTS depends_on_group VARCHAR(120) NULL;

CREATE INDEX IF NOT EXISTS idx_task_checklist_depends
    ON task_checklist (task_id, depends_on_group);
