-- Удаление «залипших» участников чатов сделок/задач.
--
-- Ранее (до 2026-09-30) get_deal_chat_room / get_task_chat_room
-- автоматически добавляли текущего юзера в ChatMember при первом
-- открытии endpoint'а. Из-за этого любой admin, кто хоть раз посмотрел
-- карточку сделки/задачи, оставался в её чате навсегда и видел
-- переписку в списке /admin/chat.
--
-- Чистим: оставляем в chat_member только тех, кто явно связан с
-- сущностью (creator / responsible / member).
-- Идемпотентно.

-- 1. Чаты сделок: оставить creator + responsible + deal_member.
DELETE FROM chat_member
WHERE room_id IN (
    SELECT id FROM chat_room WHERE kind = 'deal' AND related_deal_id IS NOT NULL
)
AND (room_id, user_id) NOT IN (
    SELECT r.id, d.creator_id FROM chat_room r JOIN deal d ON d.id = r.related_deal_id
    WHERE r.kind = 'deal' AND d.creator_id IS NOT NULL
    UNION
    SELECT r.id, d.responsible_user_id FROM chat_room r JOIN deal d ON d.id = r.related_deal_id
    WHERE r.kind = 'deal' AND d.responsible_user_id IS NOT NULL
    UNION
    SELECT r.id, dm.user_id FROM chat_room r JOIN deal_member dm ON dm.deal_id = r.related_deal_id
    WHERE r.kind = 'deal'
);

-- 2. Чаты задач: оставить creator + responsible + task_member.
DELETE FROM chat_member
WHERE room_id IN (
    SELECT id FROM chat_room WHERE kind = 'task' AND related_task_id IS NOT NULL
)
AND (room_id, user_id) NOT IN (
    SELECT r.id, t.creator_id FROM chat_room r JOIN task t ON t.id = r.related_task_id
    WHERE r.kind = 'task' AND t.creator_id IS NOT NULL
    UNION
    SELECT r.id, t.responsible_id FROM chat_room r JOIN task t ON t.id = r.related_task_id
    WHERE r.kind = 'task' AND t.responsible_id IS NOT NULL
    UNION
    SELECT r.id, tm.user_id FROM chat_room r JOIN task_member tm ON tm.task_id = r.related_task_id
    WHERE r.kind = 'task'
);
