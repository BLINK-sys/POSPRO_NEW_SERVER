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
    # Если задано — контракт подписан, КП заморожено. Любые изменения в
    # основном магазине (цены, курсы, vat_enabled складов) НЕ затрагивают
    # подписанные КП. Юзер может править строки руками и добавлять новые
    # товары — новые товары захватывают актуальные данные на момент
    # добавления и сразу попадают в снимок.
    signed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, short=False):
        result = {
            'id': self.id,
            'name': self.name,
            'total_amount': self.total_amount,
            'signed_at': self.signed_at.isoformat() if self.signed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if not short:
            result['items'] = self.items
            result['settings'] = self.settings
            result['calculator_data'] = self.calculator_data
        return result
