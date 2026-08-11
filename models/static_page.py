"""
Статические страницы сайта, редактируемые из админки через rich-text.
Одна запись = одна страница (slug уникален), контент — HTML от TipTap.

Начинаем с 'pay-delivery' (кнопка «Оплата и доставка» в шапке).
Модель универсальная — потом сюда же лягут 'about' и другие.

Старая заглушка `PageContent` не используется нигде и оставлена как есть —
эту модель `StaticPage` пишем с нуля, чтобы не тащить неудобный enum
`page ∈ ('about','contacts')` из старой заготовки.
"""

from datetime import datetime
from extensions import db


class StaticPage(db.Model):
    __tablename__ = 'static_pages'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False, default='')
    # HTML от TipTap — sanitize'd на клиенте, дополнительно чистить не надо.
    content = db.Column(db.Text, nullable=False, default='')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'slug': self.slug,
            'title': self.title or '',
            'content': self.content or '',
            'is_active': bool(self.is_active),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
