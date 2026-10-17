"""
Компании CRM — отдельная сущность рядом с `KpClient` (контакт).

Клиент может работать «один» (без компании) или числиться сотрудником
компании (`KpClient.company_id`). Один клиент = одна компания.

На сделке допускаются обе привязки независимо:
- `Deal.company_id` — одна компания (опционально)
- связка через `DealContact` — несколько контактов (опционально)

Структура полей:
  - name     : название (обязательно)
  - bin      : БИН/ИНН (строкой; у РК и РФ разные форматы)
  - address  : юр./фактический адрес (одной строкой)
  - website  : сайт
  - phone    : основной телефон
  - email    : основной e-mail
  - note     : свободные заметки
"""

from datetime import datetime
from extensions import db


class KpCompany(db.Model):
    __tablename__ = 'kp_company'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    bin = db.Column(db.String(32), nullable=True)
    address = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    note = db.Column(db.Text, nullable=True)

    # created_by — числовой FK на system_users, не ограниченный констрейнтом
    # (как и в kp_client — чтобы удаление юзера не каскадировало на компании).
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'bin': self.bin,
            'address': self.address,
            'website': self.website,
            'phone': self.phone,
            'email': self.email,
            'note': self.note,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class DealContact(db.Model):
    """
    Многие-ко-многим: сделка ↔ контакт (`kp_client`). Один из контактов
    в сделке помечается `is_primary=True` — он показывается в карточке
    канбана и в compact-виде списка сделок. Для совместимости со старым
    кодом в `Deal.client_id` синхронизируется primary.
    """
    __tablename__ = 'deal_contact'
    __table_args__ = (
        db.UniqueConstraint('deal_id', 'client_id', name='uq_deal_contact'),
    )

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='CASCADE'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('kp_client.id', ondelete='CASCADE'), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('false'))
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
