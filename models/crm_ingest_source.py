"""
Единая таблица правил автосоздания сделок:
- `kind='internal'` — триггеры из своего же бэка (обработчики заказов
  `order`, уточнений цены `price_request` и т.п.). Ищется по
  `source_key` (уникально в этой ветке).
- `kind='webhook'` — внешние источники (сторонние сайты, лендинги,
  формы Tilda, интеграции CAMPO). Приходят через
  `POST /api/webhooks/crm/ingest/<token>`. Ищется по `token` (формат
  `wh_<32hex>`, генерируется на бэке при создании).

Одна таблица вместо двух — так и админский UI (`/admin/deals/sources`)
проще (одна форма-конструктор), и код flow `_ingest` унифицирован.

CHECK constraint жёстко разделяет две ветки: у webhook'а обязан быть
`token` и NULL `source_key`, у internal'а — наоборот.
"""

from datetime import datetime

from extensions import db
from sqlalchemy.dialects.postgresql import JSONB


CRM_INGEST_KINDS = ('internal', 'webhook')
CRM_INGEST_ASSIGNMENT_STRATEGIES = ('round_robin', 'least_busy', 'fixed', 'unassigned')
CRM_INGEST_CLIENT_RESOLUTIONS = ('none', 'always_create', 'find_by_email', 'find_by_phone')
CRM_INGEST_PRIORITIES = ('low', 'normal', 'high')


class CrmIngestSource(db.Model):
    __tablename__ = 'crm_ingest_source'
    __table_args__ = (
        # Ветка ↔ поля-идентификаторы: у webhook обязан быть token и
        # NULL source_key, у internal — обязателен source_key и NULL token.
        db.CheckConstraint(
            "(kind = 'webhook' AND token IS NOT NULL AND source_key IS NULL) "
            "OR (kind = 'internal' AND source_key IS NOT NULL AND token IS NULL)",
            name='ck_crm_ingest_source_kind_identity',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False)

    # Только для internal: 'order', 'price_request', … Уникальный (частичный
    # индекс через where clause в миграции).
    source_key = db.Column(db.String(64), nullable=True)
    # Только для webhook: `wh_<32hex>`. Отдаётся админу как часть URL.
    token = db.Column(db.String(64), nullable=True)

    # Человеческое имя из формы админа — «CAMPO Magazine», «Форма Tilda».
    name = db.Column(db.String(128), nullable=False)

    pipeline_id = db.Column(db.Integer, db.ForeignKey('deal_pipeline.id', ondelete='RESTRICT'), nullable=False)
    stage_id = db.Column(db.Integer, db.ForeignKey('deal_stage.id', ondelete='RESTRICT'), nullable=False)

    # Шаблоны с плейсхолдерами вида {source_ref_id}, {client.name},
    # {amount}, {product_name}, {external_url}. Рендерятся на бэке при
    # создании сделки.
    title_template = db.Column(db.Text, nullable=False)
    notes_template = db.Column(db.Text, nullable=True)

    priority = db.Column(db.String(16), nullable=False, default='normal', server_default=db.text("'normal'"))

    # Стратегия назначения ответственного (см. CRM_INGEST_ASSIGNMENT_STRATEGIES).
    assignment_strategy = db.Column(
        db.String(16), nullable=False, default='unassigned', server_default=db.text("'unassigned'"),
    )
    # Пул system_user.id для round_robin / least_busy.
    pool_user_ids = db.Column(JSONB, nullable=False, default=list, server_default=db.text("'[]'::jsonb"))
    # Для fixed — конкретный юзер.
    fixed_user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    # Счётчик round-robin, крутится по кругу через SELECT ... FOR UPDATE.
    assignment_index = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))

    # Как искать/создавать клиента kp_client из payload.
    client_resolution = db.Column(
        db.String(24), nullable=False, default='none', server_default=db.text("'none'"),
    )

    # Дедупликация: если true и уже есть Deal с (source_ref_type,
    # source_ref_id) — возвращаем существующий вместо создания второго.
    dedupe_by_ref = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))

    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))

    # Статистика — обновляется в /webhooks/crm/ingest handler.
    last_used_at = db.Column(db.DateTime, nullable=True)
    request_count = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))

    created_by = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self, expose_token=False):
        d = {
            'id': self.id,
            'kind': self.kind,
            'source_key': self.source_key,
            'name': self.name,
            'pipeline_id': self.pipeline_id,
            'stage_id': self.stage_id,
            'title_template': self.title_template,
            'notes_template': self.notes_template,
            'priority': self.priority,
            'assignment_strategy': self.assignment_strategy,
            'pool_user_ids': self.pool_user_ids or [],
            'fixed_user_id': self.fixed_user_id,
            'client_resolution': self.client_resolution,
            'dedupe_by_ref': bool(self.dedupe_by_ref),
            'active': bool(self.active),
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'request_count': self.request_count,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        # Токен — секрет: отдаём только когда админ кликнул «показать URL»
        # или сразу после создания (см. POST /api/admin/crm-sources).
        if expose_token:
            d['token'] = self.token
        return d
