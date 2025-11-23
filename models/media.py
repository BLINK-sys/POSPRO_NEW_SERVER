from extensions import db
from sqlalchemy import Index


class ProductMedia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    media_type = db.Column(db.String(10), nullable=False)  # "image" или "video"
    order = db.Column(db.Integer, default=0)

    # ✅ Индекс для оптимизации запросов изображений
    __table_args__ = (
        Index('idx_media_product_type_order', 'product_id', 'media_type', 'order'),
    )

