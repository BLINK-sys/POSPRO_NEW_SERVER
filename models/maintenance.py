"""
Техническое обслуживание сайта («выключить магазин для всех кроме
owner»). Owner в админке создаёт заготовки сообщений (title+body) и
при выключении выбирает одну — её текст показывают всем клиентам и
сотрудникам кроме самого owner.

site_mode — одна-единственная запись (id=1) со статусом сайта.
maintenance_notice — пул готовых табличек, можно переиспользовать.
"""

from datetime import datetime
from extensions import db


class MaintenanceNotice(db.Model):
    __tablename__ = 'maintenance_notice'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False, default='', server_default='')
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False,
        server_default=db.text('NOW()'),
    )
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False,
        server_default=db.text('NOW()'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SiteMode(db.Model):
    __tablename__ = 'site_mode'
    __table_args__ = (
        db.CheckConstraint('id = 1', name='site_mode_singleton'),
    )

    id = db.Column(db.Integer, primary_key=True, default=1)
    is_maintenance = db.Column(
        db.Boolean, nullable=False, default=False,
        server_default=db.text('FALSE'),
    )
    notice_id = db.Column(
        db.Integer,
        db.ForeignKey('maintenance_notice.id', ondelete='SET NULL'),
        nullable=True,
    )
    started_at = db.Column(db.DateTime, nullable=True)
    started_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey('system_users.id', ondelete='SET NULL'),
        nullable=True,
    )
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False,
        server_default=db.text('NOW()'),
    )

    notice = db.relationship('MaintenanceNotice', lazy='joined')
