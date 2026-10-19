"""
Унифицированный справочник для «опросника при переходе стадии»:
Теплота клиента, Город, Вид деятельности, Тип бизнеса — и любые
новые, которые добавит админ. Админка — /admin/dictionaries.

Значения привязываются к сделке через `Deal.survey_values JSONB`
({<dict_code>: <item_id>}), а стадия требует набор кодов через
`DealStage.required_dict_codes JSONB`.

DealSource — отдельная таблица (у неё 2-уровневая структура с variants),
а не этот универсальный справочник.
"""

from datetime import datetime

from extensions import db


class Dictionary(db.Model):
    __tablename__ = 'dictionary'

    id = db.Column(db.Integer, primary_key=True)
    # Короткий ascii-код, используется как ключ в deal.survey_values и
    # в deal_stage.required_dict_codes. Пример: 'heat', 'city', 'activity'.
    code = db.Column(db.String(64), nullable=False, unique=True)
    label = db.Column(db.String(255), nullable=False)
    order_pos = db.Column(db.Integer, nullable=False, default=0,
                          server_default=db.text('0'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    items = db.relationship(
        'DictionaryItem', backref='dictionary',
        cascade='all, delete-orphan',
        order_by='DictionaryItem.order_pos',
    )

    def to_dict(self, with_items: bool = False) -> dict:
        d = {
            'id': self.id,
            'code': self.code,
            'label': self.label,
            'order_pos': self.order_pos,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_items:
            d['items'] = [it.to_dict() for it in self.items]
        return d


class DictionaryItem(db.Model):
    __tablename__ = 'dictionary_item'
    __table_args__ = (
        db.UniqueConstraint('dict_id', 'name', name='uq_dict_item'),
    )

    id = db.Column(db.Integer, primary_key=True)
    dict_id = db.Column(
        db.Integer, db.ForeignKey('dictionary.id', ondelete='CASCADE'),
        nullable=False,
    )
    name = db.Column(db.String(255), nullable=False)
    order_pos = db.Column(db.Integer, nullable=False, default=0,
                          server_default=db.text('0'))
    is_active = db.Column(db.Boolean, nullable=False, default=True,
                          server_default=db.text('true'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'dict_id': self.dict_id,
            'name': self.name,
            'order_pos': self.order_pos,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
