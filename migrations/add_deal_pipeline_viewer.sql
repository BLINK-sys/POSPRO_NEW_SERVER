-- Белый список юзеров, которым воронка видна в UI (dropdown + настройки).
-- Пустой список = публичная воронка. См. models.deal_pipeline.DealPipelineViewer.

CREATE TABLE IF NOT EXISTS deal_pipeline_viewer (
    pipeline_id INTEGER NOT NULL REFERENCES deal_pipeline(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    added_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (pipeline_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_deal_pipeline_viewer_user
    ON deal_pipeline_viewer(user_id);
