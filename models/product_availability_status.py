from extensions import db


class ProductAvailabilityStatus(db.Model):
    __tablename__ = 'product_availability_statuses'

    id = db.Column(db.Integer, primary_key=True)
    status_name = db.Column(db.String(255), nullable=False)  # Название статуса
    condition_operator = db.Column(db.String(10), nullable=False)  # Оператор: '>', '<', '='
    condition_value = db.Column(db.Integer, nullable=False)  # Значение для сравнения
    background_color = db.Column(db.String(7), nullable=False, default='#ffffff')  # Цвет фона в HEX
    text_color = db.Column(db.String(7), nullable=False, default='#000000')  # Цвет текста в HEX
    order = db.Column(db.Integer, default=0)  # Порядок сортировки
    active = db.Column(db.Boolean, default=True)  # Активен ли статус
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id', ondelete='SET NULL'), nullable=True)  # Поставщик

    supplier = db.relationship('Supplier', backref='availability_statuses', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'status_name': self.status_name,
            'condition_operator': self.condition_operator,
            'condition_value': self.condition_value,
            'background_color': self.background_color,
            'text_color': self.text_color,
            'order': self.order,
            'active': self.active,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.name if self.supplier else None
        }

    def get_formula_display(self):
        """Возвращает отображаемую формулу"""
        return f"Если кол-во товара \"{self.condition_operator} {self.condition_value}\" то статус \"{self.status_name}\""

    def check_condition(self, quantity):
        """Проверяет условие для заданного количества"""
        if self.condition_operator == '>':
            return quantity > self.condition_value
        elif self.condition_operator == '<':
            return quantity < self.condition_value
        elif self.condition_operator == '=':
            return quantity == self.condition_value
        elif self.condition_operator == '>=':
            return quantity >= self.condition_value
        elif self.condition_operator == '<=':
            return quantity <= self.condition_value
        return False
