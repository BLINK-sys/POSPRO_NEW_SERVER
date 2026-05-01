-- Adds the per-system-user opt-in column for the AI Product Import feature.
-- Mirrors the pattern of allowed_system_user_ids for the AI Consultant chat.
-- Default empty list — feature stays locked until owner enables specific users
-- via /admin/ai-consultant (tab "Импорт товаров").

ALTER TABLE ai_consultant_access
ADD COLUMN IF NOT EXISTS allowed_product_import_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
