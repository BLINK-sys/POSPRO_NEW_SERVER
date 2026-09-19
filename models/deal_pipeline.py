"""
Воронки сделок CRM и их стадии. Полностью настраиваются админом
(не хардкод) — см. `/admin/deals/pipelines`.

Стадия имеет три типа:
- normal — обычная колонка Kanban.
- won    — финальная выигрышная (при переносе сделки сюда `deal.status`
           автоматически переключается в 'won').
- lost   — финальная проигрышная (аналогично, 'lost').

Одна воронка «Основная» с 5 стадиями сидируется скриптом
`migrations/apply_crm_tables.py` — чтобы Kanban на старте Этапа 3 был
не пустой.
"""

from datetime import datetime

from extensions import db


DEAL_STAGE_TYPES = ('normal', 'won', 'lost')


class DealPipeline(db.Model):
    __tablename__ = 'deal_pipeline'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    # Порядок табов воронок наверху /admin/deals — drag&drop сохраняется
    # через POST /api/admin/deal-pipelines/reorder.
    order = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    stages = db.relationship(
        'DealStage',
        backref='pipeline',
        cascade='all, delete-orphan',
        order_by='DealStage.order',
    )

    def to_dict(self, include_stages=False):
        d = {
            'id': self.id,
            'name': self.name,
            'order': self.order,
            'active': bool(self.active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_stages:
            d['stages'] = [s.to_dict() for s in self.stages]
        return d


class DealStage(db.Model):
    __tablename__ = 'deal_stage'

    id = db.Column(db.Integer, primary_key=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey('deal_pipeline.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    # Hex-цвет колонки Kanban ('#22c55e' и т.п.). Дефолт — нейтрально-серый.
    color = db.Column(db.String(9), nullable=False, default='#94a3b8', server_default=db.text("'#94a3b8'"))
    order = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    # normal / won / lost — см. DEAL_STAGE_TYPES.
    type = db.Column(db.String(16), nullable=False, default='normal', server_default=db.text("'normal'"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'pipeline_id': self.pipeline_id,
            'name': self.name,
            'color': self.color,
            'order': self.order,
            'type': self.type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
