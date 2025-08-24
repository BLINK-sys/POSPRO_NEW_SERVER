from extensions import db


class ProductMedia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    media_type = db.Column(db.String(10), nullable=False)  # "image" или "video"
    order = db.Column(db.Integer, default=0)

