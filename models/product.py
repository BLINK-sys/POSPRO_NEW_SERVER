from extensions import db
from models.brand import Brand
from models.supplier import Supplier
from sqlalchemy import Index


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    article = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)

    price = db.Column(db.Float, nullable=False)
    wholesale_price = db.Column(db.Float)
    quantity = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True)
    country = db.Column(db.String(100))
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'), nullable=True)
    brand_info = db.relationship('Brand', backref='products', lazy='joined')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)
    supplier = db.relationship('Supplier', backref='products', lazy='joined')
    description = db.Column(db.Text)
    status = db.Column(db.Integer, db.ForeignKey('status.id'))
    status_info = db.relationship('Status', backref='products', lazy='joined')
    is_draft = db.Column(db.Boolean, default=True)

    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    category = db.relationship('Category')
    characteristics = db.relationship('ProductCharacteristic', backref='product', cascade='all, delete-orphan')
    media = db.relationship('ProductMedia', backref='product', cascade='all, delete-orphan')
    documents = db.relationship('ProductDocument', backref='product', cascade='all, delete-orphan')

    # ✅ Индексы для оптимизации запросов
    __table_args__ = (
        Index('idx_product_visible_draft', 'is_visible', 'is_draft'),
        Index('idx_product_brand_visible', 'brand_id', 'is_visible', 'is_draft'),
        Index('idx_product_category_visible', 'category_id', 'is_visible', 'is_draft'),
        Index('idx_product_slug', 'slug'),
    )

    def get_main_image_url(self):
        # Получаем первое изображение по порядку (order)
        # Используем связь media для избежания циклических импортов
        images = [m for m in self.media if m.media_type == 'image']
        if images:
            # Сортируем по order и берем первое
            images.sort(key=lambda x: x.order or 0)
            return images[0].url
        return ''
