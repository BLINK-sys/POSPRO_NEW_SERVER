"""
Единый чат-мессенджер CRM: комнаты, участники, сообщения, реакции,
файлы. Один и тот же движок обслуживает:
- Общий чат компании (`kind='general'`, singleton).
- Личные переписки 1-на-1 (`kind='direct'`).
- Групповые чаты по интересу (`kind='group'`).
- Автоматически создаваемые чаты сделок (`kind='deal'`, привязка через
  `related_deal_id`).
- Автоматически создаваемые чаты задач (`kind='task'`,
  `related_task_id`).

Одна лента `/admin/chat` показывает все чаты пользователя в одном
списке — сортированные по времени последнего сообщения.

Real-time доставка новых сообщений/реакций/read-mark — через SSE-поток
`/api/admin/chat/stream` (реализация в Этапе 5).
"""

from datetime import datetime

from extensions import db


CHAT_ROOM_KINDS = ('general', 'direct', 'group', 'deal', 'task')


class ChatRoom(db.Model):
    __tablename__ = 'chat_room'

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False)
    # Только для 'group' — своё название. Для остальных типов заголовок
    # рендерится клиентом (по участникам для direct, по сделке/задаче
    # для deal/task, "Общий" для general).
    name = db.Column(db.String(255), nullable=True)
    related_deal_id = db.Column(db.Integer, db.ForeignKey('deal.id', ondelete='CASCADE'), nullable=True)
    related_task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    members = db.relationship('ChatMember', backref='room', cascade='all, delete-orphan')
    messages = db.relationship(
        'ChatMessage',
        backref='room',
        cascade='all, delete-orphan',
        order_by='ChatMessage.created_at.desc()',
    )


class ChatMember(db.Model):
    __tablename__ = 'chat_member'
    __table_args__ = (
        db.UniqueConstraint('room_id', 'user_id', name='uq_chat_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('chat_room.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Для расчёта unread — время последнего прочтения сообщения в комнате.
    # Обновляется при POST /api/admin/chat/rooms/<id>/read или при чтении
    # сообщений в открытой комнате.
    last_read_at = db.Column(db.DateTime, nullable=True)


class ChatMessage(db.Model):
    __tablename__ = 'chat_message'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('chat_room.id', ondelete='CASCADE'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    text = db.Column(db.Text, nullable=True)
    # Reply-цитата: если задан, при рендере показываем контекст того
    # сообщения. NULL для обычного сообщения.
    reply_to_id = db.Column(db.Integer, db.ForeignKey('chat_message.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Редактирование разрешено в первые 5 мин — фронтовое ограничение,
    # бэк проверяет `(now - created_at) < 5 min` в PUT-ручке.
    edited_at = db.Column(db.DateTime, nullable=True)
    # Soft-delete — сообщение остаётся для целостности reply-ссылок,
    # но не показывается («Сообщение удалено»).
    deleted_at = db.Column(db.DateTime, nullable=True)

    reactions = db.relationship('ChatReaction', backref='message', cascade='all, delete-orphan')
    attachments = db.relationship('ChatAttachment', backref='message', cascade='all, delete-orphan')


class ChatReaction(db.Model):
    __tablename__ = 'chat_reaction'
    __table_args__ = (
        db.UniqueConstraint('message_id', 'user_id', 'emoji', name='uq_chat_reaction'),
    )

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_message.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'), nullable=False)
    # Одна emoji-символ или короткий shortcode. Ограничение по фронту —
    # 6 «стандартных»: 👍 ❤️ 🎉 😄 😢 👎.
    emoji = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ChatAttachment(db.Model):
    __tablename__ = 'chat_attachment'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_message.id', ondelete='CASCADE'), nullable=False)
    file_url = db.Column(db.String(1024), nullable=False)
    file_name = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
