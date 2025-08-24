# models/benefit.py

from extensions import db


class Benefit(db.Model):
    __tablename__ = 'benefits'

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(100), nullable=False)  # имя иконки Lucide
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    order = db.Column(db.Integer, default=0)
