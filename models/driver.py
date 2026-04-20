from datetime import datetime

from extensions import db


class Driver(db.Model):
    """Мастер-список драйверов, которые можно переиспользовать в нескольких товарах."""
    __tablename__ = 'drivers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(255))
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.BigInteger)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, usage_count=None):
        d = {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'is_active': self.is_active,
            'order': self.order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if usage_count is not None:
            d['usage_count'] = usage_count
        return d
