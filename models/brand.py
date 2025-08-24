from extensions import db


class Brand(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # ✅ автоинкремент
    name = db.Column(db.String(255), nullable=False)
    country = db.Column(db.String(255))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(512))  # ссылка или путь
