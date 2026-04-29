-- Single-row table that controls who can use the AI Consultant (/ai page).
-- Owner (bocan.anton@mail.ru) edits via /api/admin/ai-consultant/settings.
-- All flags default to FALSE — feature stays locked until explicitly opened.

CREATE TABLE IF NOT EXISTS ai_consultant_access (
    id SERIAL PRIMARY KEY,
    allow_guest BOOLEAN NOT NULL DEFAULT FALSE,
    allow_registered BOOLEAN NOT NULL DEFAULT FALSE,
    allow_wholesale BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_system_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by_email VARCHAR(255)
);

-- Seed the singleton row so first read returns defaults instead of NULL.
INSERT INTO ai_consultant_access (allow_guest, allow_registered, allow_wholesale, allowed_system_user_ids)
SELECT FALSE, FALSE, FALSE, '[]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM ai_consultant_access);
