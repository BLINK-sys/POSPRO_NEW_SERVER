from extensions import db
import datetime


class Order(db.Model):
    """Модель заказа"""
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_number = db.Column(db.String(50), unique=True, nullable=False)  # Уникальный номер заказа
    
    # Статус заказа (связь с таблицей статусов)
    status_id = db.Column(db.Integer, db.ForeignKey('order_statuses.id'), nullable=False)  # Связь с таблицей статусов
    
    # Статусы оплаты
    payment_status = db.Column(db.String(50), nullable=False, default='unpaid')  # unpaid, paid, refunded
    payment_method = db.Column(db.String(50))  # cash, card, transfer, etc.
    
    # Суммы
    subtotal = db.Column(db.Float, nullable=False)  # Сумма товаров
    total_amount = db.Column(db.Float, nullable=False)  # Итоговая сумма
    
    # Контактная информация
    customer_name = db.Column(db.String(255))
    customer_phone = db.Column(db.String(50))
    customer_email = db.Column(db.String(255))
    
    # Адрес доставки
    delivery_address = db.Column(db.Text)
    delivery_method = db.Column(db.String(100))  # pickup, delivery, etc.
    
    # Комментарии
    customer_comment = db.Column(db.Text)
    admin_comment = db.Column(db.Text)
    
    # Даты
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    confirmed_at = db.Column(db.DateTime)
    shipped_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref='orders', lazy=True)
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan', lazy=True)
    status_info = db.relationship('OrderStatus', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'order_number': self.order_number,
            'status_id': self.status_id,
            'status_info': self.status_info.to_dict() if self.status_info else None,
            'payment_status': self.payment_status,
            'payment_method': self.payment_method,
            'subtotal': float(self.subtotal) if self.subtotal else 0,
            'total_amount': float(self.total_amount) if self.total_amount else 0,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'customer_email': self.customer_email,
            'delivery_address': self.delivery_address,
            'delivery_method': self.delivery_method,
            'customer_comment': self.customer_comment,
            'admin_comment': self.admin_comment,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
            'shipped_at': self.shipped_at.isoformat() if self.shipped_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'items': [item.to_dict() for item in self.items] if self.items else [],
            'items_count': len(self.items) if self.items else 0,
            'user': {
                'id': self.user.id,
                'email': self.user.email,
                'phone': self.user.phone,
                'name': self.user.get_display_name()
            } if self.user else None,
            'manager': self.manager_assignment.to_dict() if hasattr(self, 'manager_assignment') and self.manager_assignment else None
        }


class OrderItem(db.Model):
    """Модель товара в заказе"""
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    
    # Информация о товаре на момент заказа (для истории)
    product_name = db.Column(db.String(255), nullable=False)
    product_price = db.Column(db.Float, nullable=False)
    product_article = db.Column(db.String(100))
    
    quantity = db.Column(db.Integer, nullable=False)
    price_per_item = db.Column(db.Float, nullable=False)  # Цена за единицу на момент заказа
    total_price = db.Column(db.Float, nullable=False)  # quantity * price_per_item

    # Relationships
    product = db.relationship('Product', backref='order_items', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'product_price': float(self.product_price) if self.product_price else 0,
            'product_article': self.product_article,
            'quantity': self.quantity,
            'price_per_item': float(self.price_per_item) if self.price_per_item else 0,
            'total_price': float(self.total_price) if self.total_price else 0,
            'product': {
                'id': self.product.id,
                'name': self.product.name,
                'slug': self.product.slug,
                'image_url': self.product.get_main_image_url() if self.product else None,
                'current_price': self.product.price,
                'status': self.product.status_info.to_dict() if self.product and self.product.status_info and hasattr(self.product.status_info, 'to_dict') else None
            } if self.product else None
        }
