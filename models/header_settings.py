"""
Модели конфигурации шапки сайта (admin → Страницы → Шапка).

Три сущности:
  - HeaderSettings — single-row: настройки строки уведомления
    (жёлтая полоса поверх шапки). Текст + опциональная ссылка,
    флаг «кликабельно» + «в новой вкладке».
  - HeaderMenuItem — пункт нижней полосы категорий шапки. Двух видов:
      kind='category' — ссылка на существующую Category (category_id).
      kind='custom'   — собственный «раздел» с курируемым списком
                        товаров. Уникальный slug для URL /category/<slug>.
  - HeaderMenuItemProduct — товары кастомного раздела (M:N через
    промежуточную таблицу с order — под drag-and-drop).

Порядок пунктов в нижней полосе задаётся `order` у HeaderMenuItem.
Скрыть пункт без удаления → `is_active=False`.
"""

from datetime import datetime
from extensions import db


class HeaderSettings(db.Model):
    __tablename__ = 'header_settings'

    id = db.Column(db.Integer, primary_key=True)

    # Строка уведомления (жёлтая полоса сверху)
    strip_enabled = db.Column(db.Boolean, nullable=False, default=False)
    strip_text = db.Column(db.String(500), nullable=False, default='')
    strip_clickable = db.Column(db.Boolean, nullable=False, default=False)
    strip_url = db.Column(db.String(500), nullable=False, default='')
    strip_open_new_tab = db.Column(db.Boolean, nullable=False, default=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'strip_enabled': bool(self.strip_enabled),
            'strip_text': self.strip_text or '',
            'strip_clickable': bool(self.strip_clickable),
            'strip_url': self.strip_url or '',
            'strip_open_new_tab': bool(self.strip_open_new_tab),
        }


class HeaderMenuItem(db.Model):
    __tablename__ = 'header_menu_items'

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)  # 'category' | 'custom'
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    order = db.Column(db.Integer, nullable=False, default=0)

    # Self-referential parent для вложенных пунктов. Только для kind='custom'
    # (у category-ref нет своих children — они бы дублировали подкатегории
    # реальной Category). null = пункт верхнего уровня (нижняя полоса шапки).
    # ON DELETE CASCADE — при удалении родителя удаляются все потомки.
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey('header_menu_items.id', ondelete='CASCADE'),
        nullable=True,
    )
    # Флаг: у этого custom-пункта режим «вложенные категории» вместо
    # «своих товаров». Если True — в шапке кнопка открывает dropdown с
    # children; если False — переход на /category/<slug> с товарами.
    has_children_mode = db.Column(db.Boolean, nullable=False, default=False)

    # Для kind='category'
    category_id = db.Column(
        db.Integer,
        db.ForeignKey('category.id', ondelete='CASCADE'),
        nullable=True,
    )

    # Для kind='custom'
    custom_name = db.Column(db.String(200), nullable=True)
    # Уникальный slug для URL /category/<slug>. Проверяем на пересечение
    # со slug'ами реальных категорий на уровне admin-роута (не в БД, т.к.
    # это разные таблицы).
    custom_slug = db.Column(db.String(200), nullable=True, unique=True)

    # ── Индивидуальный стиль кнопки в шапке ─────────────────────────
    # Все поля опциональны. Если ни одно не задано — кнопка рендерится
    # дефолтным стилем ссылки (см. header.tsx нижняя полоса категорий).
    border_enabled = db.Column(db.Boolean, nullable=False, default=False)
    border_color = db.Column(db.String(20), nullable=True)   # #RRGGBB
    bg_color = db.Column(db.String(20), nullable=True)
    text_color = db.Column(db.String(20), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    products = db.relationship(
        'HeaderMenuItemProduct',
        backref='menu_item',
        cascade='all, delete-orphan',
        order_by='HeaderMenuItemProduct.order',
    )


class HeaderMenuItemProduct(db.Model):
    __tablename__ = 'header_menu_item_products'

    id = db.Column(db.Integer, primary_key=True)
    menu_item_id = db.Column(
        db.Integer,
        db.ForeignKey('header_menu_items.id', ondelete='CASCADE'),
        nullable=False,
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('product.id', ondelete='CASCADE'),
        nullable=False,
    )
    order = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('menu_item_id', 'product_id', name='uq_header_menu_item_product'),
    )
