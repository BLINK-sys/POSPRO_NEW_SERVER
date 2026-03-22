import datetime
from extensions import db


class SiteVisitor(db.Model):
    __tablename__ = 'site_visitors'

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)
    device_type = db.Column(db.String(10), nullable=False)  # 'web' or 'mobile'
    user_agent = db.Column(db.Text)
    visited_at = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_visitor_ip_device_date', 'ip_address', 'device_type', 'visited_at'),
    )
