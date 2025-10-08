from extensions import db


class ProductCharacteristic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    key = db.Column(db.String(255), nullable=False)  # Будем хранить ID характеристики как строку
    value = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
