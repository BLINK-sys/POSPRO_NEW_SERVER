-- Компании CRM (`kp_company`) + мультисвязь сделка<->контакт (`deal_contact`)
-- + FK `kp_client.company_id` и `deal.company_id`.
-- См. models.kp_company.{KpCompany, DealContact}.

CREATE TABLE IF NOT EXISTS kp_company (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    bin VARCHAR(32) NULL,
    address TEXT NULL,
    website VARCHAR(255) NULL,
    phone VARCHAR(64) NULL,
    email VARCHAR(255) NULL,
    note TEXT NULL,
    created_by INTEGER NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kp_company_name ON kp_company(name);
CREATE INDEX IF NOT EXISTS idx_kp_company_bin ON kp_company(bin);

-- Контакт -> компания (опциональный FK, SET NULL при удалении компании).
ALTER TABLE kp_client
    ADD COLUMN IF NOT EXISTS company_id INTEGER NULL
        REFERENCES kp_company(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_kp_client_company_id ON kp_client(company_id);

-- Сделка -> компания (опциональный FK, SET NULL при удалении).
ALTER TABLE deal
    ADD COLUMN IF NOT EXISTS company_id INTEGER NULL
        REFERENCES kp_company(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_deal_company_id ON deal(company_id);

-- Мультисвязь сделка<->контакт. is_primary — отмечает основной контакт
-- сделки для обратной совместимости с deal.client_id (который держим
-- синхронизированным в коде).
CREATE TABLE IF NOT EXISTS deal_contact (
    id SERIAL PRIMARY KEY,
    deal_id INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES kp_client(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    added_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_deal_contact UNIQUE (deal_id, client_id)
);

CREATE INDEX IF NOT EXISTS idx_deal_contact_deal ON deal_contact(deal_id);
CREATE INDEX IF NOT EXISTS idx_deal_contact_client ON deal_contact(client_id);

-- Бэкфил: для существующих сделок с client_id — создаём primary-запись
-- в deal_contact, чтобы мульти-контакты старых сделок начинались с 1 основного.
INSERT INTO deal_contact (deal_id, client_id, is_primary, added_at)
SELECT id, client_id, TRUE, NOW()
FROM deal
WHERE client_id IS NOT NULL
ON CONFLICT (deal_id, client_id) DO NOTHING;
