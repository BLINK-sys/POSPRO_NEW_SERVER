from extensions import db


class SystemBrand(db.Model):
    __tablename__ = 'system_brands'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, nullable=False)
    order = db.Column(db.Integer, default=0)
