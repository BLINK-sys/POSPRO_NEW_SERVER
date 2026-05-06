from extensions import db
from datetime import datetime


class KpClient(db.Model):
    """
    Клиент в адресной книге для коммерческих предложений.

    Это shared-пул на всех системных пользователей: любой менеджер видит
    всех клиентов и может их редактировать. Так нужно потому что один
    клиент может работать с несколькими менеджерами и его данные не должны
    дублироваться.

    Поля заполняются по-разному в зависимости от `organization_type`:
      'too'        : organization_name + bin + full_name (директор)
      'ip'         : organization_name + iin + full_name (директор/владелец)
      'individual' : full_name + iin (organization_name пуст)

    `phone` и `whatsapp` опциональны для всех типов. `note` — свободная
    заметка менеджера.

    КП ссылается на клиента через `KPHistory.client_id`, причём именно
    через id (детальные данные не дублируются — Q6 в спеке). Удалить
    клиента можно только если на него не ссылается ни одна запись
    `kp_history` (Q4 в спеке).
    """
    __tablename__ = 'kp_client'

    id = db.Column(db.Integer, primary_key=True)
    organization_type = db.Column(db.String(20), nullable=False)  # too|ip|individual

    organization_name = db.Column(db.String(255), nullable=True)
    full_name = db.Column(db.String(255), nullable=True)  # директор для too/ip, ФИО для individual
    bin = db.Column(db.String(20), nullable=True)
    iin = db.Column(db.String(20), nullable=True)

    phone = db.Column(db.String(50), nullable=True)
    whatsapp = db.Column(db.String(50), nullable=True)

    note = db.Column(db.Text, nullable=True)

    # Кто создал — для аудита, не используется для гейтинга доступа.
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def display_name(self) -> str:
        """Имя для списка/чипа: название организации для ТОО/ИП, ФИО для физлица."""
        if self.organization_type in ('too', 'ip') and self.organization_name:
            return self.organization_name
        return self.full_name or '—'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'organization_type': self.organization_type,
            'organization_name': self.organization_name,
            'full_name': self.full_name,
            'bin': self.bin,
            'iin': self.iin,
            'phone': self.phone,
            'whatsapp': self.whatsapp,
            'note': self.note,
            'display_name': self.display_name,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
