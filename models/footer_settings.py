from extensions import db


class FooterSetting(db.Model):
    __tablename__ = 'footer_settings'

    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text)
    instagram_url = db.Column(db.String(255))
    whatsapp_url = db.Column(db.String(255))
    telegram_url = db.Column(db.String(255))
    phone = db.Column(db.String(100))
    email = db.Column(db.String(255))
    address = db.Column(db.String(255))
    working_hours = db.Column(db.String(255))
