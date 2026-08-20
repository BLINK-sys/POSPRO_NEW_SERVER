"""
CustomerActivity — единый event-log действий покупателей (не admin/system).

Три типа событий:
  - 'search'         — юзер отправил поиск на /search. payload: query, results_count.
  - 'category_view'  — юзер зашёл на /category/<slug>. payload: category_id + snapshot имени.
  - 'brand_view'     — юзер зашёл на /brand/<brand>. payload: brand_id + snapshot имени.

Что писать / не писать — решает бэк-эндпоинт трекинга:
  - Если в JWT role='admin' или 'system' — пропускаем (админам не считаем).
  - Bot-фильтр по User-Agent (тот же список, что в dashboard.track_product_view).
  - Дедуп category_view / brand_view 5 мин по IP+entity_id (аналогично product_views).

FK на category/brand/user — ON DELETE SET NULL, чтобы удаление сущности
не терло исторические логи (snapshot имени сохраняется в отдельном поле).
"""

import datetime
from extensions import db


class CustomerActivity(db.Model):
    __tablename__ = 'customer_activity_events'

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(32), nullable=False)  # 'search' | 'category_view' | 'brand_view'

    # Общие поля
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
    )
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    # Payload — заполняются в зависимости от event_type
    search_query = db.Column(db.String(500))     # для 'search'
    results_count = db.Column(db.Integer)         # для 'search'
    category_id = db.Column(
        db.Integer,
        db.ForeignKey('category.id', ondelete='SET NULL'),
        nullable=True,
    )
    category_name = db.Column(db.String(255))    # snapshot на момент события
    category_slug = db.Column(db.String(255))
    brand_id = db.Column(
        db.Integer,
        db.ForeignKey('brand.id', ondelete='SET NULL'),
        nullable=True,
    )
    brand_name = db.Column(db.String(255))       # snapshot

    __table_args__ = (
        db.Index('idx_customer_activity_type_date', 'event_type', 'created_at'),
        db.Index('idx_customer_activity_query', 'search_query'),
        db.Index('idx_customer_activity_category', 'category_id'),
        db.Index('idx_customer_activity_brand', 'brand_id'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'event_type': self.event_type,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'user_agent': (self.user_agent or '')[:200],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'query': self.search_query,
            'results_count': self.results_count,
            'category_id': self.category_id,
            'category_name': self.category_name,
            'category_slug': self.category_slug,
            'brand_id': self.brand_id,
            'brand_name': self.brand_name,
        }
