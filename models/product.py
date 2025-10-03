from extensions import db


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
    brand = db.Column(db.String(100))
    description = db.Column(db.Text)
    status = db.Column(db.Integer, db.ForeignKey('status.id'))
    status_info = db.relationship('Status', backref='products', lazy='joined')
    is_draft = db.Column(db.Boolean, default=True)

    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    category = db.relationship('Category')
    characteristics = db.relationship('ProductCharacteristic', backref='product', cascade='all, delete-orphan')
    media = db.relationship('ProductMedia', backref='product', cascade='all, delete-orphan')
    documents = db.relationship('ProductDocument', backref='product', cascade='all, delete-orphan')

    def get_main_image_url(self):
        # Получаем первое изображение по порядку (order)
        # Используем связь media для избежания циклических импортов
        images = [m for m in self.media if m.media_type == 'image']
        if images:
            # Сортируем по order и берем первое
            images.sort(key=lambda x: x.order or 0)
            return images[0].url
        return ''
