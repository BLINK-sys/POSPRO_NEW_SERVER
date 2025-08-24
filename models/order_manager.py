from extensions import db
import datetime


class OrderManager(db.Model):
    """Модель для связи заказов с менеджерами"""
    __tablename__ = 'order_managers'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    manager_id = db.Column(db.Integer, db.ForeignKey('system_users.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.datetime.now)
    assigned_by = db.Column(db.Integer, db.ForeignKey('system_users.id'))  # Кто назначил менеджера
    
    # Relationships
    order = db.relationship('Order', backref=db.backref('manager_assignment', uselist=False), lazy=True)
    manager = db.relationship('SystemUser', foreign_keys=[manager_id], backref='assigned_orders', lazy=True)
    assigned_by_user = db.relationship('SystemUser', foreign_keys=[assigned_by], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'manager_id': self.manager_id,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'assigned_by': self.assigned_by,
            'manager': {
                'id': self.manager.id,
                'full_name': self.manager.full_name,
                'email': self.manager.email,
                'phone': self.manager.phone
            } if self.manager else None,
            'assigned_by_user': {
                'id': self.assigned_by_user.id,
                'full_name': self.assigned_by_user.full_name
            } if self.assigned_by_user else None
        }
