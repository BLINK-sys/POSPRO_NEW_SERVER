"""
Справочник «Источник сделки» — куда менеджер классифицирует откуда
пришла сделка (Instagram, 2GIS, холодный звонок, выставка и т.п.).
Заполняется админом в /admin/deals/sources.

Прикрепляется к сделке через `Deal.source_id`. При автосоздании сделки
через ingest-источник (CrmIngestSource) — проставляется автоматически
из `CrmIngestSource.default_deal_source_id`, если он задан.
"""

from datetime import datetime

from extensions import db


class DealSource(db.Model):
    __tablename__ = 'deal_source'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    # Hex-цвет для чипа в карточке сделки/списке (#RRGGBB). Опционально —
    # NULL → фронт отрисует нейтральным.
    color = db.Column(db.String(9), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    # Выключенные источники остаются в БД (чтобы старые сделки не теряли
    # ссылку), но не предлагаются в селекте «Новая сделка».
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'sort_order': self.sort_order,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
