from extensions import db


class Supplier(db.Model):
    """Модель справочника поставщиков"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)  # Название поставщика
    contact_person = db.Column(db.String(255))  # Контактное лицо
    phone = db.Column(db.String(50))  # Телефон
    email = db.Column(db.String(255))  # Email
    address = db.Column(db.Text)  # Адрес
    description = db.Column(db.Text)  # Описание
    
    def to_dict(self):
        """Преобразует объект в словарь для JSON"""
        return {
            'id': self.id,
            'name': self.name,
            'contact_person': self.contact_person,
            'phone': self.phone,
            'email': self.email,
            'address': self.address,
            'description': self.description
        }

