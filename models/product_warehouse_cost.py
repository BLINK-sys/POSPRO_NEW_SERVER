from extensions import db
from datetime import datetime


class ProductWarehouseCost(db.Model):
    __tablename__ = 'product_warehouse_cost'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False)
    cost_price = db.Column(db.Float, nullable=False)
    calculated_price = db.Column(db.Float, nullable=True)
    calculated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    product = db.relationship('Product', backref='warehouse_costs', lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('product_id', 'warehouse_id', name='uq_product_warehouse'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'product_article': self.product.article if self.product else None,
            'product_slug': self.product.slug if self.product else None,
            'warehouse_id': self.warehouse_id,
            'cost_price': self.cost_price,
            'calculated_price': self.calculated_price,
            'calculated_at': self.calculated_at.isoformat() if self.calculated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
