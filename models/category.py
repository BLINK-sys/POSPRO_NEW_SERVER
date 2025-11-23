from extensions import db
from sqlalchemy import Index


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(255), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    show_in_menu = db.Column(db.Boolean, nullable=False, default=True)

    # ✅ Индексы для оптимизации запросов
    __table_args__ = (
        Index('idx_category_slug', 'slug'),
        Index('idx_category_parent', 'parent_id'),
        Index('idx_category_menu', 'show_in_menu', 'parent_id'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'parent_id': self.parent_id,
            'description': self.description,
            'image_url': self.image_url,
            'order': self.order,
            'show_in_menu': self.show_in_menu
        }