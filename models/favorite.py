from flask import g
from extensions import db
from datetime import datetime

from models.product_availability_status import ProductAvailabilityStatus


def _get_availability_status(quantity: int):
    """Возвращает статус наличия на основе таблицы product_availability_statuses"""
    statuses = getattr(g, '_product_availability_statuses_cache', None)
    if statuses is None:
        statuses = ProductAvailabilityStatus.query.filter_by(active=True).order_by(ProductAvailabilityStatus.order).all()
        g._product_availability_statuses_cache = statuses

    for status in statuses:
        if status.check_condition(quantity):
            return status.to_dict()
    return None


class Favorite(db.Model):
    __tablename__ = 'favorites'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Отношения
    user = db.relationship('User', backref='favorites')
    product = db.relationship('Product', backref='favorites')
    
    # Уникальный ключ для предотвращения дублирования
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id', name='unique_user_product_favorite'),)
    
    def to_dict(self):
        product_data = None

        if self.product:
            brand_info = None
            if self.product.brand_info:
                brand_info = {
                    'id': self.product.brand_info.id,
                    'name': self.product.brand_info.name,
                    'country': self.product.brand_info.country,
                    'description': self.product.brand_info.description,
                    'image_url': self.product.brand_info.image_url
                }

            product_data = {
                'id': self.product.id,
                'name': self.product.name,
                'slug': self.product.slug,
                'price': self.product.price,
                'article': self.product.article,
                'image_url': self.product.get_main_image_url(),
                'quantity': self.product.quantity,
                'status': self.product.status_info.to_dict() if self.product.status_info else None,
                'category': self.product.category.to_dict() if getattr(self.product, 'category', None) and hasattr(self.product.category, 'to_dict') else None,
                'brand_id': self.product.brand_id,
                'brand_info': brand_info,
                'availability_status': _get_availability_status(self.product.quantity or 0)
            }

        return {
            'id': self.id,
            'user_id': self.user_id,
            'product_id': self.product_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'product': product_data
        }
