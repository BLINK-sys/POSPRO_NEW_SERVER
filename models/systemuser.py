from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash


class SystemUser(db.Model):
    __tablename__ = 'system_users'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(50))
    password_hash = db.Column(db.String(255), nullable=False)

    # Права доступа
    access_orders = db.Column(db.Boolean, default=False)
    access_catalog = db.Column(db.Boolean, default=False)
    access_clients = db.Column(db.Boolean, default=False)
    access_users = db.Column(db.Boolean, default=False)
    access_settings = db.Column(db.Boolean, default=False)
    access_dashboard = db.Column(db.Boolean, default=False)
    access_brands = db.Column(db.Boolean, default=False)
    access_statuses = db.Column(db.Boolean, default=False)
    access_pages = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
