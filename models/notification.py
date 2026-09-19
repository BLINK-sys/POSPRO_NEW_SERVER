"""
Уведомления пользователей + подписки на Web Push.

Три слоя доставки уведомления:
1. Bell-иконка + панель в шапке админки — читает через
   `GET /api/admin/notifications`.
2. Красные точки на pill'ах CRM/Сделки/Задачи/Чат — читает через
   счётчики `?unread_by_section=1`.
3. Web Push — когда вкладка админки не активна или закрыта. Подписки
   хранятся в `web_push_subscription`, сервер шлёт push через `pywebpush`
   с VAPID-ключами из env.

Kinds уведомлений (не enum-таблица, просто набор строк для UI):
- deal_assigned          — тебя назначили ответственным за сделку
- deal_stage_changed     — стадия моей сделки изменилась
- deal_won / deal_lost   — сделка закрыта
- deal_ingest_arrived    — новая сделка из ingest'а на unassigned-очереди
                           (для менеджеров-охотников)
- task_assigned          — тебя назначили ответственным за задачу
- task_status_changed    — статус моей задачи изменился
- task_due_soon          — 24 часа до дедлайна
- task_overdue           — дедлайн прошёл, задача не done
- chat_mention           — тебя @упомянули в чате
- chat_new_message       — новое сообщение в комнате, где я участник
                           (агрегированное — не по одному сообщению)
"""

from datetime import datetime

from extensions import db
from sqlalchemy.dialects.postgresql import JSONB


# Секции UI для маршрутизации красных точек в шапке админки.
NOTIFICATION_SECTIONS = ('deals', 'tasks', 'chat')


class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), nullable=False)
    kind = db.Column(db.String(48), nullable=False)
    # Куда красить красную точку в шапке админки (deals/tasks/chat).
    section = db.Column(db.String(16), nullable=False)
    # Опциональная привязка к сущности — клик по уведомлению ведёт туда.
    entity_type = db.Column(db.String(16), nullable=True)  # deal/task/chat_room
    entity_id = db.Column(db.Integer, nullable=True)
    # Свободный JSON: имена, суммы, что попало — фронт форматирует.
    payload = db.Column(JSONB, nullable=False, default=dict, server_default=db.text("'{}'::jsonb"))
    read_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'kind': self.kind,
            'section': self.section,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'payload': self.payload or {},
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class WebPushSubscription(db.Model):
    """
    Подписка браузера на Push API. Один юзер — несколько подписок
    (по одному на браузер/устройство). При отправке push мы шлём во ВСЕ.

    `endpoint` — URL Push-сервиса (FCM/Mozilla/…), от него зависит какой
    именно браузер получит push. Уникальный.

    `keys` — публичные ключи браузера (`p256dh` + `auth`) для шифрования
    payload'а. Приходят от `PushManager.subscribe()`.
    """
    __tablename__ = 'web_push_subscription'
    __table_args__ = (
        db.UniqueConstraint('endpoint', name='uq_web_push_endpoint'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), nullable=False)
    endpoint = db.Column(db.String(1024), nullable=False)
    keys = db.Column(JSONB, nullable=False)  # {p256dh, auth}
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    def to_web_push_info(self):
        """Формат для pywebpush.webpush()."""
        return {
            'endpoint': self.endpoint,
            'keys': self.keys or {},
        }


class UserPresence(db.Model):
    """
    Онлайн-статус пользователя. Обновляется heartbeat'ом от активной
    админ-вкладки (Этап 6.5 — фронт). Считаем «онлайн» если
    `last_heartbeat > now - 60 сек`.

    Уже есть `system_users.last_seen` из /admin/user-activity, но там
    гранулярность 60 сек и без явного heartbeat_at из фронта. Тут
    точнее — админ мог быть в браузере с открытой админкой но не
    делать запросов (например, читает страницу).
    """
    __tablename__ = 'user_presence'

    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), primary_key=True)
    last_heartbeat_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    current_section = db.Column(db.String(32), nullable=True)  # deals/tasks/chat/other

    def is_online(self) -> bool:
        if not self.last_heartbeat_at:
            return False
        return (datetime.utcnow() - self.last_heartbeat_at).total_seconds() < 60
