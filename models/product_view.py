import datetime
from extensions import db


class ProductView(db.Model):
    __tablename__ = 'product_views'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False)
    product_name = db.Column(db.String(500))
    product_slug = db.Column(db.String(500))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    view_type = db.Column(db.String(20), default='detail')  # 'detail' or 'quick'
    viewed_at = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_product_view_date', 'product_id', 'viewed_at'),
    )
