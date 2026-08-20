# models/homepage_block.py

from extensions import db


class HomepageBlock(db.Model):
    __tablename__ = 'homepage_blocks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)  # ✅ Добавлено поле описания
    type = db.Column(db.String(50), nullable=False)  # categories / products / brands
    order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)  # ✅ Добавлено поле активности
    carusel = db.Column(db.Boolean, default=False)

    # ✅ Новые поля:
    show_title = db.Column(db.Boolean, default=True)
    title_align = db.Column(db.String(20), default='left')  # left, right, center

    # Кастомизация внешнего вида блока товаров (тип 'products'):
    # background_color — hex-цвет фона карточки-обёртки блока; NULL =
    # дефолт (сейчас bg-gray-100). show_products_categories_filter — тогл
    # для полосы «Все категории / Денежные ящики / …» над списком товаров.
    background_color = db.Column(db.String(9), nullable=True)  # #RRGGBB(AA)
    show_products_categories_filter = db.Column(db.Boolean, default=True, nullable=False)

    items = db.relationship('HomepageBlockItem', back_populates='block', cascade="all, delete-orphan")
