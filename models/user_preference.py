"""
Пользовательские настройки UI: произвольный `key` → JSONB `value`
на юзера.

Используется для сохранения состояний фильтров/вьюх, которые не хочется
хранить в localStorage (чтобы ехали между устройствами). Первый use-case —
фильтры канбана сделок (`key='deals_canvas'`): период, клиент, компания,
ответственный.

Схема простая, без миграций на добавление новых ключей — каждый клиент
кладёт туда что ему надо под уникальным именем.
"""

from datetime import datetime
from extensions import db
from sqlalchemy.dialects.postgresql import JSONB


class UserPreference(db.Model):
    __tablename__ = 'user_preferences'

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('system_users.id', ondelete='CASCADE'),
        primary_key=True,
    )
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(JSONB, nullable=False, default=dict,
                      server_default=db.text("'{}'::jsonb"))
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
        nullable=False,
    )
