-- Архивация чатов удалённых сделок/задач.
--
-- Если у чата удалённой сущности была переписка/вложения, мы не
-- сносим его CASCADE, а помечаем is_archived=true и отвязываем от
-- удалённой сделки/задачи (related_*_id = NULL). Пустые чаты удаляются.
--
-- Идемпотентная миграция.

ALTER TABLE chat_room
    ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE chat_room
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL;

-- Индекс для быстрой фильтрации активных чатов в списке комнат.
CREATE INDEX IF NOT EXISTS idx_chat_room_archived
    ON chat_room (is_archived);

-- Существующие orphan-чаты (ссылаются на удалённые сделки/задачи):
-- если есть сообщения, архивируем; иначе удаляем.

-- 1. Пустые чаты сделок с несуществующим related_deal_id — удалить.
DELETE FROM chat_room
WHERE kind = 'deal'
  AND related_deal_id IS NOT NULL
  AND related_deal_id NOT IN (SELECT id FROM deal)
  AND NOT EXISTS (SELECT 1 FROM chat_message WHERE room_id = chat_room.id);

-- 2. Не пустые чаты сделок с несуществующим related_deal_id — архивировать.
UPDATE chat_room SET
    is_archived = TRUE,
    archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP),
    name = COALESCE(name, 'Сделка #' || related_deal_id),
    related_deal_id = NULL
WHERE kind = 'deal'
  AND related_deal_id IS NOT NULL
  AND related_deal_id NOT IN (SELECT id FROM deal);

-- 3. Пустые чаты задач с несуществующим related_task_id — удалить.
DELETE FROM chat_room
WHERE kind = 'task'
  AND related_task_id IS NOT NULL
  AND related_task_id NOT IN (SELECT id FROM task)
  AND NOT EXISTS (SELECT 1 FROM chat_message WHERE room_id = chat_room.id);

-- 4. Не пустые чаты задач с несуществующим related_task_id — архивировать.
UPDATE chat_room SET
    is_archived = TRUE,
    archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP),
    name = COALESCE(name, 'Задача #' || related_task_id),
    related_task_id = NULL
WHERE kind = 'task'
  AND related_task_id IS NOT NULL
  AND related_task_id NOT IN (SELECT id FROM task);
