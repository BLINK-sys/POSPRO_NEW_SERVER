from extensions import db
import datetime


class Cart(db.Model):
    """Модель корзины покупок"""
    __tablename__ = 'cart'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    # Уникальный индекс для предотвращения дублирования одного товара
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id', name='_user_product_cart_uc'),)

    # Relationships
    user = db.relationship('User', backref='cart_items', lazy=True)
    product = db.relationship('Product', backref='in_carts', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'product': {
                'id': self.product.id,
                'name': self.product.name,
                'slug': self.product.slug,
                'price': self.product.price,
                'article': self.product.article,
                'image_url': self.product.get_main_image_url() if self.product else None,
                'status': self.product.status_info.to_dict() if self.product and self.product.status_info else None,
                'category': self.product.category.to_dict() if self.product and self.product.category else None,
                'quantity_available': self.product.quantity
            } if self.product else None,
            'total_price': float(self.product.price * self.quantity) if self.product and self.product.price else 0
        }
