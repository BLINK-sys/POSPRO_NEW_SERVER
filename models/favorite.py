from extensions import db
from datetime import datetime


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
        return {
            'id': self.id,
            'user_id': self.user_id,
            'product_id': self.product_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'product': {
                'id': self.product.id,
                'name': self.product.name,
                'slug': self.product.slug,
                'price': self.product.price,
                'article': self.product.article,
                'image_url': self.product.get_main_image_url() if self.product else None,
                'status': self.product.status_info.to_dict() if self.product.status_info else None,
                'category': self.product.category.to_dict() if self.product.category else None
            } if self.product else None
        }
