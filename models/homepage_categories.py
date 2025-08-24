# models/homepage_categories.py

from extensions import db


class HomepageCategory(db.Model):
    __tablename__ = 'homepage_categories'

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, nullable=False)
    order = db.Column(db.Integer, default=0)
