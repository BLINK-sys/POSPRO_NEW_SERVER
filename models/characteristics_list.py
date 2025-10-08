from extensions import db

class CharacteristicsList(db.Model):
    __tablename__ = 'characteristics_list'
    
    id = db.Column(db.Integer, primary_key=True)
    characteristic_key = db.Column(db.String(100), nullable=False, unique=True)
    unit_of_measurement = db.Column(db.String(50), nullable=True)
    
    def __repr__(self):
        return f'<CharacteristicsList {self.characteristic_key}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'characteristic_key': self.characteristic_key,
            'unit_of_measurement': self.unit_of_measurement
        }
