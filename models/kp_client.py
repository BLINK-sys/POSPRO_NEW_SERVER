from extensions import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB


class KpClient(db.Model):
    """
    Клиент в адресной книге для коммерческих предложений.

    Это shared-пул на всех системных пользователей: любой менеджер видит
    всех клиентов и может их редактировать. Так нужно потому что один
    клиент может работать с несколькими менеджерами и его данные не должны
    дублироваться.

    Минимальная схема (после миграции 2026-06-XX, выпилившей TOO/ИП/физлицо):
      - full_name : ФИО клиента (обязательно)
      - object    : свободное текстовое поле — название объекта/проекта,
                    адрес, название организации, что угодно
      - contacts  : JSONB-массив `[{phone, note}]` — телефоны клиента с
                    произвольными заметками типа «WhatsApp», «секретарь»,
                    «после 18:00» и т.п. Несколько контактов на одного клиента.

    КП ссылается на клиента через `KPHistory.client_id`. Удалить клиента
    можно только если на него не ссылается ни одна запись `kp_history`.
    """
    __tablename__ = 'kp_client'

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(255), nullable=True)
    object = db.Column(db.Text, nullable=True)
    contacts = db.Column(JSONB, nullable=False, default=list, server_default='[]')

    # Кто создал — для аудита, не используется для гейтинга доступа.
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def display_name(self) -> str:
        """Имя для списка/чипа: ФИО (а если пусто — Объект)."""
        return self.full_name or self.object or '—'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'full_name': self.full_name,
            'object': self.object,
            'contacts': self.contacts or [],
            'display_name': self.display_name,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
