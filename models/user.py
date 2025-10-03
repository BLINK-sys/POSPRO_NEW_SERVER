from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    organization_type = db.Column(db.String(20), nullable=False)  # individual, ip, too

    # Физ лицо
    full_name = db.Column(db.String(255))

    # ИП
    iin = db.Column(db.String(12))
    ip_name = db.Column(db.String(255))

    # ТОО
    bin = db.Column(db.String(12))
    too_name = db.Column(db.String(255))

    # Общие поля
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    delivery_address = db.Column(db.Text, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_wholesale = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_display_name(self):
        """Получить отображаемое имя пользователя в зависимости от типа организации"""
        if self.organization_type == 'individual' and self.full_name:
            return self.full_name
        elif self.organization_type == 'ip' and self.ip_name:
            return self.ip_name
        elif self.organization_type == 'too' and self.too_name:
            return self.too_name
        else:
            return self.email  # Возвращаем email как fallback