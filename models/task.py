"""
Задачи CRM (Битрикс-подобные): свободные, опционально привязанные к
сделке и/или клиенту. Ответственный — `task.responsible_id`;
соисполнители и наблюдатели — через `TaskMember` с ролью.

Статусы:
- pending        — только создана, ещё не в работе
- in_progress    — взята в работу
- waiting_check  — исполнитель ждёт приёмки от постановщика
- done           — завершена
- paused         — приостановлена
"""

from datetime import datetime

from extensions import db
from sqlalchemy.dialects.postgresql import JSONB


TASK_PRIORITIES = ('low', 'normal', 'high', 'urgent')
TASK_STATUSES = ('pending', 'in_progress', 'waiting_check', 'done', 'paused')

TASK_MEMBER_ROLES = ('co-worker', 'observer')

TASK_ACTIVITY_KINDS = (
    'created',
    'status_changed',
    'responsible_changed',
    'member_added',
    'member_removed',
    'due_at_changed',
    'checklist_added',
    'checklist_toggled',
    'checklist_removed',
    'comment',
    'field_changed',
)


class Task(db.Model):
    __tablename__ = 'task'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    # Rich-text HTML (TipTap на фронте). Для plain-search в будущем можно
    # добавить denormalized `title_search` — пока не делаем, MVP.
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(16), nullable=False, default='normal', server_default=db.text("'normal'"))
    status = db.Column(db.String(20), nullable=False, default='pending', server_default=db.text("'pending'"))

    # Постановщик и ответственный. Оба обязательны для нормального
    # задачного flow, но при удалении юзера — обнуляем (задача остаётся
    # в архиве). Наблюдатели/соисполнители — в `TaskMember`.
    creator_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    responsible_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)

    # Опциональные привязки — задача может быть свободной.
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='SET NULL'), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey('kp_client.id', ondelete='SET NULL'), nullable=True)

    started_at = db.Column(db.DateTime, nullable=True)   # когда перевели в in_progress
    due_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    tags = db.Column(JSONB, nullable=False, default=list, server_default=db.text("'[]'::jsonb"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    members = db.relationship('TaskMember', backref='task', cascade='all, delete-orphan')
    checklist = db.relationship(
        'TaskChecklist',
        backref='task',
        cascade='all, delete-orphan',
        order_by='TaskChecklist.order',
    )
    activities = db.relationship(
        'TaskActivity',
        backref='task',
        cascade='all, delete-orphan',
        order_by='TaskActivity.created_at.desc()',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'priority': self.priority,
            'status': self.status,
            'creator_id': self.creator_id,
            'responsible_id': self.responsible_id,
            'deal_id': self.deal_id,
            'client_id': self.client_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'due_at': self.due_at.isoformat() if self.due_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'tags': self.tags or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskMember(db.Model):
    """
    Соисполнители (`co-worker`) и наблюдатели (`observer`) задачи.
    Ответственный — в `Task.responsible_id`.
    """
    __tablename__ = 'task_member'
    __table_args__ = (
        db.UniqueConstraint('task_id', 'user_id', name='uq_task_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='co-worker', server_default=db.text("'co-worker'"))
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TaskChecklist(db.Model):
    __tablename__ = 'task_checklist'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('false'))
    order = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TaskActivity(db.Model):
    __tablename__ = 'task_activity'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    kind = db.Column(db.String(32), nullable=False)
    payload = db.Column(JSONB, nullable=False, default=dict, server_default=db.text("'{}'::jsonb"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
