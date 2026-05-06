from extensions import db
from datetime import datetime


class KPShare(db.Model):
    """
    Шаринг конкретного КП от владельца другому системному пользователю.

    Создаётся явно через UI (кнопка «Поделиться» на карточке КП). На каждой
    паре (kp_history_id, shared_with_user_id) уникальная запись.

    `access_level`:
        'view'  — только просмотр, нельзя править/подписывать/удалять
        'edit'  — полный доступ КРОМЕ удаления и пере-шаринга. Удалить КП
                  может только владелец (создатель). Пере-шарить — только
                  владелец или super-admin.
    """
    __tablename__ = 'kp_share'

    id = db.Column(db.Integer, primary_key=True)
    kp_history_id = db.Column(
        db.Integer,
        db.ForeignKey('kp_history.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    shared_with_user_id = db.Column(db.Integer, nullable=False, index=True)
    access_level = db.Column(db.String(16), nullable=False, default='view')
    # Кто поделился — для аудита и UI («поделился: <name>»)
    created_by = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('kp_history_id', 'shared_with_user_id', name='uq_kp_share_target'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'kp_history_id': self.kp_history_id,
            'shared_with_user_id': self.shared_with_user_id,
            'access_level': self.access_level,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class KPSuperAdminAccess(db.Model):
    """
    Single-row settings — кому owner выдал право видеть ВСЕ КП всех юзеров
    (полный доступ). Аналогично шаблону `ai_consultant_access`.

    Owner всегда имеет права независимо от этого списка (см. SystemUser.is_owner).
    Этот список — для grant'ов другим системникам.
    """
    __tablename__ = 'kp_super_admin_access'

    id = db.Column(db.Integer, primary_key=True)
    # JSON-список system_users.id. Пустой по умолчанию — никто кроме owner'а
    # не имеет глобального доступа.
    allowed_user_ids = db.Column(db.JSON, default=list, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_email = db.Column(db.String(255))

    def to_dict(self):
        return {
            'id': self.id,
            'allowed_user_ids': list(self.allowed_user_ids or []),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by_email': self.updated_by_email,
        }

    @classmethod
    def get_or_create(cls):
        row = cls.query.first()
        if not row:
            row = cls(allowed_user_ids=[])
            db.session.add(row)
            db.session.commit()
        return row
