from extensions import db


class Banner(db.Model):
    __tablename__ = 'banners'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    subtitle = db.Column(db.String(255))
    image = db.Column(db.String(512), nullable=False)
    order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)

    button_text = db.Column(db.String(255))  # ✅ Новое поле
    button_link = db.Column(db.String(512))  # ✅ Новое поле
    show_button = db.Column(db.Boolean, default=False)  # ✅ Новое поле
    open_in_new_tab = db.Column(db.Boolean, default=False)  # ✅ Новое поле
    button_color = db.Column(db.String(7), default="#000000")  # ✅ Новое поле (hex цвет)
    button_text_color = db.Column(db.String(7), default="#ffffff")  # ✅ Новое поле (hex цвет)
