"""
Модели логов AI-фич магазина.

Две независимых группы логов:

1. AIImportLog — попытки импорта товара через "PosPro AI помощник"
   (форма создания товара в админке). Один лог на одну попытку,
   статус обновляется по мере прохождения по флоу:

     error              — AI / парсер вернул ошибку
     imported           — AI вытянул данные, но юзер не сохранил товар
     saved              — товар реально создан в магазине

   Импорт доступен только админам и допущенным системным пользователям,
   поэтому user всегда из таблицы system_users.

2. AIChatSession + AIChatMessage — переписка пользователя с AI
   консультантом (на /ai). Сессия = одно открытие чата (UUID хранится
   в localStorage браузера). Доступна всем категориям пользователей,
   включая гостей. user_role: 'guest' / 'client' / 'wholesale'
   / 'system' / 'admin'. Полный текст сохраняется для всех — нужен для
   разбора качества ответов AI.
"""

import uuid
from datetime import datetime

from extensions import db


# Возможные статусы импорта. Хранятся как короткие коды, отображаемые
# названия — на стороне UI (тогда легко локализовать или поменять).
IMPORT_STATUS_ERROR = 'error'           # «Ошибка импорта»
IMPORT_STATUS_IMPORTED = 'imported'     # «Импортирован, но не сохранён»
IMPORT_STATUS_SAVED = 'saved'           # «Добавлен в магазин»


class AIImportLog(db.Model):
    __tablename__ = 'ai_import_logs'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Кто пытался импортировать. user_id может занулиться если юзера
    # потом удалят — email/role денормализованы для отображения в логах.
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True, index=True)
    user_email = db.Column(db.String(255), nullable=False)
    user_role = db.Column(db.String(20), nullable=False, default='system')  # 'admin' | 'system'

    source_url = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=IMPORT_STATUS_ERROR, index=True)

    # Что AI вытащил (если получилось). JSON: {name, description,
    # characteristics_count, images_count}. Для error может быть пустым.
    imported_data = db.Column(db.JSON, nullable=True)

    # Заполняется когда юзер реально нажал "Сохранить" в форме товара.
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='SET NULL'), nullable=True)
    product_name = db.Column(db.String(255), nullable=True)  # денорм на случай удаления товара

    error_message = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'user_role': self.user_role,
            'source_url': self.source_url,
            'status': self.status,
            'imported_data': self.imported_data,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'error_message': self.error_message,
        }


class AIChatSession(db.Model):
    """
    Одна сессия чата = одно открытие /ai в браузере. Сессия живёт пока
    юзер не очистит localStorage / не получит новый client_session_token.
    Может содержать множество сообщений во времени.
    """
    __tablename__ = 'ai_chat_sessions'

    id = db.Column(db.Integer, primary_key=True)
    # Уникальный токен сессии — идентификатор от клиента (UUID), нужен
    # чтобы append-message-эндпоинт мог найти / создать сессию без
    # авторизации (для гостей).
    client_session_token = db.Column(db.String(64), nullable=False, unique=True, index=True)

    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Профиль пользователя на момент создания сессии. Для гостей всё
    # null кроме user_role='guest'. Для авторизованных дублируем имя/email
    # чтобы лог оставался читаемым после удаления юзера.
    user_role = db.Column(db.String(20), nullable=False, default='guest', index=True)
    # 'guest' | 'client' | 'wholesale' | 'system' | 'admin'

    # FK гибкие — если в pospro 2 источника пользователей (клиенты и
    # системники), храним только id и тип, без жёсткого FK.
    user_id = db.Column(db.Integer, nullable=True, index=True)
    user_email = db.Column(db.String(255), nullable=True)
    user_name = db.Column(db.String(255), nullable=True)

    message_count = db.Column(db.Integer, default=0, nullable=False)

    messages = db.relationship(
        'AIChatMessage',
        backref='session',
        cascade='all, delete-orphan',
        order_by='AIChatMessage.created_at',
        lazy='dynamic',
    )

    def to_dict(self, include_messages=False):
        d = {
            'id': self.id,
            'client_session_token': self.client_session_token,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
            'user_role': self.user_role,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'user_name': self.user_name,
            'message_count': self.message_count,
        }
        if include_messages:
            d['messages'] = [m.to_dict() for m in self.messages]
        return d


class AIChatMessage(db.Model):
    __tablename__ = 'ai_chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('ai_chat_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    role = db.Column(db.String(20), nullable=False)  # 'user' | 'assistant'
    content = db.Column(db.Text, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'role': self.role,
            'content': self.content,
        }


def generate_session_token() -> str:
    """Хелпер для генерации UUID если клиент не передал свой."""
    return uuid.uuid4().hex
