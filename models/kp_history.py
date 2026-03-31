from extensions import db
from datetime import datetime


class KPHistory(db.Model):
    __tablename__ = 'kp_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    user_role = db.Column(db.String(20), nullable=False, default='admin')
    name = db.Column(db.String(255), nullable=False, default='')
    items = db.Column(db.JSON, nullable=False, default=list)
    settings = db.Column(db.JSON, nullable=False, default=dict)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    calculator_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, short=False):
        result = {
            'id': self.id,
            'name': self.name,
            'total_amount': self.total_amount,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if not short:
            result['items'] = self.items
            result['settings'] = self.settings
            result['calculator_data'] = self.calculator_data
        return result
