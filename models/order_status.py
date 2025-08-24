from extensions import db


class OrderStatus(db.Model):
    """Модель статусов заказов с настраиваемыми цветами"""
    __tablename__ = 'order_statuses'
    
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)  # Отображаемое название
    description = db.Column(db.Text)  # Описание статуса
    background_color = db.Column(db.String(7), nullable=False, default='#e5e7eb')  # Цвет фона (hex)
    text_color = db.Column(db.String(7), nullable=False, default='#374151')  # Цвет текста (hex)
    order = db.Column(db.Integer, default=0)  # Порядок отображения
    is_active = db.Column(db.Boolean, default=True)  # Активен ли статус
    is_final = db.Column(db.Boolean, default=False)  # Финальный статус (delivered, cancelled)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'background_color': self.background_color,
            'text_color': self.text_color,
            'order': self.order,
            'is_active': self.is_active,
            'is_final': self.is_final
        }
