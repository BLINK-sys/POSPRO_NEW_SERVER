-- Adds the per-system-user opt-in column for visibility/access to the
-- /admin/ai-consultant page itself (the AI Settings section).
-- Only the owner (bocan.anton@mail.ru) can edit this list.
-- Owner is always implicitly granted access regardless of this list.

ALTER TABLE ai_consultant_access
ADD COLUMN IF NOT EXISTS allowed_settings_admin_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
