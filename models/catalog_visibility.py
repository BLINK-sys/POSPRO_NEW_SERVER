from extensions import db
from datetime import datetime


class CatalogVisibility(db.Model):
    __tablename__ = 'catalog_visibility'

    id = db.Column(db.Integer, primary_key=True)
    catalog_type = db.Column(db.String(20), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'catalog_type': self.catalog_type,
            'enabled': self.enabled,
        }
