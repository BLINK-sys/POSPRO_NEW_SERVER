"""
SectionCard — карточка «раздела» магазина для главной страницы.

Идея: админ создаёт набор карточек (плитки с изображением, описанием и
таргетом). Затем на странице /admin/pages в блоке типа `section_cards`
выбираются нужные карточки из этого пула — в любом порядке (drag&drop).

Одна карточка = один таргет:
  target='link'       → клик ведёт на link_url (внешний/внутренний URL).
                        Флаг link_new_tab открывает в новой вкладке.
  target='categories' → клик ведёт на /section/<slug> (агрегатор товаров
                        из привязанных категорий) — новая страница, которая
                        собирает товары из всех связанных категорий и их
                        подкатегорий. Порядок категорий сохраняется, но
                        на визуал самой страницы пока не влияет.

Slug уникальный (глобально для section_cards, отдельно от category.slug —
это разные роуты: /category/<slug> vs /section/<slug>). Генерится авто
из name (safe_slugify + суффикс -N при коллизии). Админ может
перебить slug вручную в диалоге редактирования.

Два изображения:
  image_url        — маленькая карточка (сетка на главной)
  banner_image_url — hero на странице /section/<slug>
Оба опциональны и независимы.
"""

from datetime import datetime
from extensions import db


class SectionCard(db.Model):
    __tablename__ = 'section_cards'

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)

    image_url = db.Column(db.String(512), nullable=True)
    banner_image_url = db.Column(db.String(512), nullable=True)

    # 'link' | 'categories'
    target = db.Column(db.String(20), nullable=False, default='link')

    # Для target='link'
    link_url = db.Column(db.String(512), nullable=True)
    link_new_tab = db.Column(db.Boolean, nullable=False, default=False)

    order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categories = db.relationship(
        'SectionCardCategory',
        backref='section_card',
        cascade='all, delete-orphan',
        order_by='SectionCardCategory.order',
    )

    def to_dict(self, include_categories: bool = True) -> dict:
        data = {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description or '',
            'image_url': self.image_url or '',
            'banner_image_url': self.banner_image_url or '',
            'target': self.target,
            'link_url': self.link_url or '',
            'link_new_tab': bool(self.link_new_tab),
            'order': self.order,
            'active': bool(self.active),
        }
        if include_categories:
            data['category_ids'] = [c.category_id for c in self.categories]
        return data


class SectionCardCategory(db.Model):
    __tablename__ = 'section_card_categories'

    id = db.Column(db.Integer, primary_key=True)
    section_card_id = db.Column(
        db.Integer,
        db.ForeignKey('section_cards.id', ondelete='CASCADE'),
        nullable=False,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey('category.id', ondelete='CASCADE'),
        nullable=False,
    )
    order = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint(
            'section_card_id', 'category_id',
            name='uq_section_card_categories_card_category',
        ),
    )
