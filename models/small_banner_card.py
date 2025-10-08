# models/small_banner.py
from extensions import db


class SmallBanner(db.Model):
    __tablename__ = 'small_banners'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255), nullable=True)
    background_image_url = db.Column(db.String(255), nullable=True)  # ✅ Добавлено поле фонового изображения
    title_text_color = db.Column(db.String(7), nullable=True, default='#000000')  # ✅ Цвет текста заголовка
    description_text_color = db.Column(db.String(7), nullable=True, default='#666666')  # ✅ Цвет текста описания
    button_text = db.Column(db.String(100), nullable=True)
    button_text_color = db.Column(db.String(20), nullable=True)
    button_bg_color = db.Column(db.String(20), nullable=True)
    button_link = db.Column(db.String(255), nullable=True)
    card_bg_color = db.Column(db.String(20), nullable=True)
    show_button = db.Column(db.Boolean, default=True)
    open_in_new_tab = db.Column(db.Boolean, default=False)  # ✅ Новое поле
