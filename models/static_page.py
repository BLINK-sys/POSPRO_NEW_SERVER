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
    # Оформление H1-заголовка на самой странице. На <title> вкладки и
    # на SEO-метаданные эти поля не влияют — там всегда используется `title`.
    title_color = db.Column(db.String(16))  # hex, напр. '#1e293b'; null = дефолт
    title_align = db.Column(db.String(16), default='left')  # left | center | right
    title_hidden = db.Column(db.Boolean, nullable=False, default=False)  # не рендерить H1 на странице
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'slug': self.slug,
            'title': self.title or '',
            'content': self.content or '',
            'is_active': bool(self.is_active),
            'title_color': self.title_color or '',
            'title_align': self.title_align or 'left',
            'title_hidden': bool(self.title_hidden),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
