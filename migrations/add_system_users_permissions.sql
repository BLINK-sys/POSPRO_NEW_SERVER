-- Ролевая модель для SystemUser: три флага, которые управляют
-- специальными правами. Владельцу (is_owner=TRUE) флаги не нужны —
-- он всегда всё видит и может.
--
-- Идемпотентная миграция.

ALTER TABLE system_users
    ADD COLUMN IF NOT EXISTS can_see_all_deals BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE system_users
    ADD COLUMN IF NOT EXISTS can_see_all_tasks BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE system_users
    ADD COLUMN IF NOT EXISTS can_manage_pipelines BOOLEAN NOT NULL DEFAULT FALSE;
