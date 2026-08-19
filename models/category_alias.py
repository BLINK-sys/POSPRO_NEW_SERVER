"""
CategoryAlias — маппинг «имя категории от поставщика → наша канонич.
категория». Даёт идемпотентность при автовыгрузке (bio/equip): сколько
бы раз поставщик ни прислал «Пароконвектоматы», товар всегда ложится в
ту же категорию, что и раньше.

Уникальность по (source, parent_id, lower(alias_name)):
  - source различает поставщиков (bio, equip, ...); NULL = вручную заведён
    алиас админом (например seed при миграции существующих категорий).
  - parent_id даёт возможность иметь одинаковое имя в разных ветках дерева
    (например «Ножи» под «Кухня» и «Ножи» под «Огород» — разные категории).
  - alias_name храним как есть, но сравниваем case-insensitive через
    lower() на уровне запроса.

Флаги:
  - is_auto: True если строка создана резолвером автоматически
    (для фильтров в админ-UI: показать «что не проверено»).
  - needs_review: True если fuzzy-совпадение предложило смерджить и
    админ должен подтвердить/переназначить.
"""

from datetime import datetime
from sqlalchemy import Index, UniqueConstraint
from extensions import db


class CategoryAlias(db.Model):
    __tablename__ = 'category_alias'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(32), nullable=True)  # 'bio' / 'equip' / NULL
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id', ondelete='CASCADE'), nullable=True)
    alias_name = db.Column(db.String(255), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id', ondelete='CASCADE'), nullable=False)
    is_auto = db.Column(db.Boolean, nullable=False, default=False)
    needs_review = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # Уникальность на уровне БД. Case-insensitive проверку делаем в
        # запросе через LOWER(alias_name), а вот сохраняем как приходит,
        # поэтому CI-уникальность здесь не через unique-constraint, а через
        # запрос-фильтр в resolver'е (см. services/category_resolver.py).
        UniqueConstraint('source', 'parent_id', 'alias_name', name='uq_category_alias_source_parent_name'),
        Index('idx_category_alias_lookup', 'source', 'parent_id'),
        Index('idx_category_alias_category', 'category_id'),
        Index('idx_category_alias_review', 'needs_review'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'parent_id': self.parent_id,
            'alias_name': self.alias_name,
            'category_id': self.category_id,
            'is_auto': self.is_auto,
            'needs_review': self.needs_review,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
