-- Активность стадии: false = скрыта в UI, но данные сохраняются.
ALTER TABLE deal_stage
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
