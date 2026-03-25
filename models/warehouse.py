from extensions import db
from datetime import datetime


class Warehouse(db.Model):
    __tablename__ = 'warehouse'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(255))
    address = db.Column(db.Text)
    currency_id = db.Column(db.Integer, db.ForeignKey('currency.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    supplier = db.relationship('Supplier', backref='warehouses', lazy='joined')
    currency = db.relationship('Currency', backref='warehouses', lazy='joined')
    variables = db.relationship('WarehouseVariable', backref='warehouse',
                                cascade='all, delete-orphan', order_by='WarehouseVariable.sort_order')
    formula = db.relationship('WarehouseFormula', backref='warehouse',
                              uselist=False, cascade='all, delete-orphan')
    product_costs = db.relationship('ProductWarehouseCost', backref='warehouse',
                                    cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.name if self.supplier else None,
            'name': self.name,
            'city': self.city,
            'address': self.address,
            'currency_id': self.currency_id,
            'currency': self.currency.to_dict() if self.currency else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def to_dict_full(self):
        result = self.to_dict()
        result['variables'] = [v.to_dict() for v in self.variables]
        result['formula'] = self.formula.to_dict() if self.formula else None
        return result


class WarehouseVariable(db.Model):
    __tablename__ = 'warehouse_variable'

    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    label = db.Column(db.String(255))
    formula = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('warehouse_id', 'name', name='uq_warehouse_variable_name'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'warehouse_id': self.warehouse_id,
            'name': self.name,
            'label': self.label,
            'formula': self.formula,
            'sort_order': self.sort_order
        }


class WarehouseFormula(db.Model):
    __tablename__ = 'warehouse_formula'

    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False, unique=True)
    formula = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'warehouse_id': self.warehouse_id,
            'formula': self.formula,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
