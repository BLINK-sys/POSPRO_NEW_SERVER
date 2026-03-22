import datetime
from extensions import db


class SiteRequest(db.Model):
    __tablename__ = 'site_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_type = db.Column(db.String(20), nullable=False)  # 'order' or 'price_inquiry'
    customer_name = db.Column(db.String(255))
    customer_phone = db.Column(db.String(50))
    customer_email = db.Column(db.String(255))
    product_name = db.Column(db.String(255))
    product_slug = db.Column(db.String(255))
    total_amount = db.Column(db.Float, nullable=True)
    assigned_to = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_request_type_date', 'request_type', 'created_at'),
    )
