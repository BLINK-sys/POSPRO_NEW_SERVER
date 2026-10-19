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
from sqlalchemy.dialects.postgresql import JSONB


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
    # Активна ли стадия. false = скрыта в канбане и в селектах стадий
    # (кроме случая когда у текущей сделки эта стадия — тогда остаётся
    # в селекте, помечена «архив»). Удалять стадию с привязанными
    # сделками Postgres не даст (ondelete='RESTRICT' на deal.stage_id):
    # UI должен подсказать деактивировать вместо удаления.
    is_active = db.Column(db.Boolean, nullable=False, default=True,
                          server_default=db.text('true'))
    # Коды справочников (Dictionary.code), обязательные при переходе В эту
    # стадию. Если какой-то из них не заполнен в deal.survey_values —
    # move_deal вернёт 400 с missing_codes, фронт покажет модалку-опросник.
    # Пример: ['heat', 'city']. См. models.dictionary.
    required_dict_codes = db.Column(
        JSONB, nullable=False, default=list,
        server_default=db.text("'[]'::jsonb"),
    )
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
            'is_active': bool(self.is_active),
            'required_dict_codes': list(self.required_dict_codes or []),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class DealPipelineViewer(db.Model):
    """
    Белый список пользователей, которым воронка видна в UI (dropdown на
    /admin/deals + в настройках). Если для воронки список ПУСТОЙ — она
    считается публичной (видна всем). Если в списке есть хоть одна запись
    — видна только owner / can_see_all_deals / can_manage_pipelines + юзерам
    из этого списка.

    Это ТОЛЬКО фильтр списка воронок — не меняет _visible_deals_query.
    То есть если менеджер responsible по сделке из «закрытой» воронки,
    куда его в viewers не добавили, он всё равно откроет сделку по прямой
    ссылке и будет видеть/править её (как и раньше). Просто в dropdown
    этой воронки у него не будет.
    """
    __tablename__ = 'deal_pipeline_viewer'

    pipeline_id = db.Column(
        db.Integer,
        db.ForeignKey('deal_pipeline.id', ondelete='CASCADE'),
        primary_key=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('system_users.id', ondelete='CASCADE'),
        primary_key=True,
    )
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
