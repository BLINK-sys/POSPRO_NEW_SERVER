"""
Модель для справочника характеристик
"""

from extensions import db
from datetime import datetime

class CharacteristicsList(db.Model):
    """Модель справочника характеристик"""
    
    __tablename__ = 'characteristics_list'
    
    id = db.Column(db.Integer, primary_key=True)
    characteristic_key = db.Column(db.String(100), nullable=False, unique=True)
    unit_of_measurement = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<CharacteristicsList {self.characteristic_key}>'
    
    def to_dict(self):
        """Преобразует объект в словарь"""
        return {
            'id': self.id,
            'characteristic_key': self.characteristic_key,
            'unit_of_measurement': self.unit_of_measurement,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def get_all(cls):
        """Получить все характеристики"""
        return cls.query.order_by(cls.characteristic_key).all()
    
    @classmethod
    def get_by_key(cls, key):
        """Получить характеристику по ключу"""
        return cls.query.filter_by(characteristic_key=key).first()
    
    @classmethod
    def create(cls, characteristic_key, unit_of_measurement=None):
        """Создать новую характеристику"""
        characteristic = cls(
            characteristic_key=characteristic_key,
            unit_of_measurement=unit_of_measurement
        )
        db.session.add(characteristic)
        db.session.commit()
        return characteristic
    
    def update(self, characteristic_key=None, unit_of_measurement=None):
        """Обновить характеристику"""
        if characteristic_key is not None:
            self.characteristic_key = characteristic_key
        if unit_of_measurement is not None:
            self.unit_of_measurement = unit_of_measurement
        
        self.updated_at = datetime.utcnow()
        db.session.commit()
        return self
    
    def delete(self):
        """Удалить характеристику"""
        db.session.delete(self)
        db.session.commit()
        return True
