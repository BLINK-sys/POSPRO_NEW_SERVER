# models/homepage_block_title.py

from extensions import db


class HomepageBlockItem(db.Model):
    __tablename__ = 'homepage_block_items'

    id = db.Column(db.Integer, primary_key=True)
    block_id = db.Column(db.Integer, db.ForeignKey('homepage_blocks.id'), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)  # ID категории, товара или бренда
    order = db.Column(db.Integer, default=0)

    block = db.relationship('HomepageBlock', back_populates='items')

