"""
Сделка CRM + её м2м-связи (участники, прикреплённые КП, привязанные
заказы) + лента активности.

Сделка — центральная сущность CRM. Живёт внутри воронки/стадии
(`pipeline_id` + `stage_id`), имеет ответственного (`responsible_user_id`),
клиента из адресной книги (`client_id` → `kp_client.id`) и опциональные
поля-метаданные (amount, currency, priority, source, tags, notes).

Поля `source_ref_type` + `source_ref_id` — откуда пришла сделка:
- Для сделок, созданных вручную менеджером — оба NULL.
- Для сделок, созданных через ingest (внутренний или webhook) —
  `source_ref_type` совпадает с `crm_ingest_source.source_key`
  (internal, напр. 'order', 'price_request') или имеет форму
  `webhook:<token_prefix>` (для внешних). `source_ref_id` — id объекта
  во внешней/родной системе (order_id, price_request_id, external_ref).
  Индекс `(source_ref_type, source_ref_id)` обеспечивает быстрый lookup
  для дедупликации: пришёл второй webhook с тем же ref_id → возвращаем
  существующий deal_id вместо создания второй сделки.
"""

from datetime import datetime

from extensions import db
from sqlalchemy.dialects.postgresql import JSONB


DEAL_PRIORITIES = ('low', 'normal', 'high')
DEAL_SOURCES = ('site', 'incoming', 'cold', 'warm', 'referral', 'ingest')
DEAL_STATUSES = ('open', 'won', 'lost')

DEAL_MEMBER_ROLES = ('participant', 'observer')

DEAL_ACTIVITY_KINDS = (
    'created',
    'created_from_source',
    'stage_changed',
    'responsible_changed',
    'member_added',
    'member_removed',
    'kp_attached',
    'kp_detached',
    'order_attached',
    'order_detached',
    'comment',
    'field_changed',
)


class Deal(db.Model):
    __tablename__ = 'deal'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('kp_client.id', ondelete='SET NULL'), nullable=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('deal_pipeline.id', ondelete='RESTRICT'), nullable=False)
    stage_id = db.Column(db.Integer, db.ForeignKey('deal_stage.id', ondelete='RESTRICT'), nullable=False)

    amount = db.Column(db.Numeric(14, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=False, default='KZT', server_default=db.text("'KZT'"))
    expected_close_at = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(16), nullable=False, default='normal', server_default=db.text("'normal'"))
    source = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(16), nullable=False, default='open', server_default=db.text("'open'"))
    tags = db.Column(JSONB, nullable=False, default=list, server_default=db.text("'[]'::jsonb"))
    notes = db.Column(db.Text, nullable=True)

    # Ingest-провенанс.
    source_ref_type = db.Column(db.String(64), nullable=True)
    source_ref_id = db.Column(db.String(128), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    members = db.relationship('DealMember', backref='deal', cascade='all, delete-orphan')
    kps = db.relationship('DealKp', backref='deal', cascade='all, delete-orphan')
    orders_link = db.relationship('DealOrder', backref='deal', cascade='all, delete-orphan')
    activities = db.relationship(
        'DealActivity',
        backref='deal',
        cascade='all, delete-orphan',
        order_by='DealActivity.created_at.desc()',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'client_id': self.client_id,
            'responsible_user_id': self.responsible_user_id,
            'pipeline_id': self.pipeline_id,
            'stage_id': self.stage_id,
            'amount': float(self.amount) if self.amount is not None else None,
            'currency': self.currency,
            'expected_close_at': self.expected_close_at.isoformat() if self.expected_close_at else None,
            'priority': self.priority,
            'source': self.source,
            'status': self.status,
            'tags': self.tags or [],
            'notes': self.notes,
            'source_ref_type': self.source_ref_type,
            'source_ref_id': self.source_ref_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class DealMember(db.Model):
    """
    Участники и наблюдатели сделки (помимо `Deal.responsible_user_id`,
    который «главный»). Наблюдатель — read-only + уведомления, участник —
    может редактировать и комментировать.
    """
    __tablename__ = 'deal_member'
    __table_args__ = (
        db.UniqueConstraint('deal_id', 'user_id', name='uq_deal_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='participant', server_default=db.text("'participant'"))
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class DealKp(db.Model):
    """Прикреплённые КП (many-to-many: одна сделка → несколько версий КП)."""
    __tablename__ = 'deal_kp'
    __table_args__ = (
        db.UniqueConstraint('deal_id', 'kp_history_id', name='uq_deal_kp'),
    )

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='CASCADE'), nullable=False)
    kp_history_id = db.Column(db.Integer, db.ForeignKey('kp_history.id', ondelete='CASCADE'), nullable=False)
    attached_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    attached_by = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)


class DealOrder(db.Model):
    """Привязанные к сделке заказы (many-to-many)."""
    __tablename__ = 'deal_order'
    __table_args__ = (
        db.UniqueConstraint('deal_id', 'order_id', name='uq_deal_order'),
    )

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='CASCADE'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    attached_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class DealActivity(db.Model):
    """Лента событий сделки (аудит-лог)."""
    __tablename__ = 'deal_activity'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='CASCADE'), nullable=False)
    # Для системных событий (например, ingest) user_id = NULL.
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    kind = db.Column(db.String(32), nullable=False)
    payload = db.Column(JSONB, nullable=False, default=dict, server_default=db.text("'{}'::jsonb"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'deal_id': self.deal_id,
            'user_id': self.user_id,
            'kind': self.kind,
            'payload': self.payload or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
