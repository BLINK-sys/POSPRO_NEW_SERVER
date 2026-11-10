"""
Сквозной модуль файлов для сделок и задач. Полиморфная связь через
`(entity_type, entity_id)`.

Для файлов внутри сообщений чата используется отдельная таблица
`chat_attachment` (см. `chat.py`) — там файл семантически принадлежит
сообщению, а не сущности.
"""

from datetime import datetime

from extensions import db


ENTITY_TYPES = ('deal', 'task', 'project')


class EntityAttachment(db.Model):
    __tablename__ = 'entity_attachment'

    id = db.Column(db.Integer, primary_key=True)
    # Полиморфная привязка. FK на конкретную таблицу не создаём — чистится
    # через триггер приложения при удалении сделки/задачи (см. cascade в
    # соответствующих моделях).
    entity_type = db.Column(db.String(16), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)

    file_url = db.Column(db.String(1024), nullable=False)
    file_name = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)

    # Пользовательский заголовок документа. Отображается в UI над файлом
    # (например «Договор № 42» / «Скан паспорта»). Пусто → UI показывает
    # оригинальное `file_name`.
    title = db.Column(db.String(255), nullable=True)

    uploaded_by = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'file_url': self.file_url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'title': self.title,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class EntityAttachmentVersion(db.Model):
    """
    История сохранений одного attachment'а — каждая новая запись через
    PUT /raw (встроенный редактор) создаёт здесь снимок предыдущей
    версии файла. Лимит 30: при добавлении 31-й самая старая удаляется
    (вместе со своим файлом на диске).

    Сам файл хранится рядом с основным: `<основной путь>.v<version_id>`
    (например `/disk/uploads/entities/task/42/0017_contract.xlsx.v132`).
    При удалении EntityAttachment каскадом удаляются и все версии
    (`ondelete=CASCADE` ниже) — файлы чистит бизнес-логика в
    routes/entity_attachments.py.
    """
    __tablename__ = 'entity_attachment_version'

    id = db.Column(db.Integer, primary_key=True)
    attachment_id = db.Column(
        db.Integer,
        db.ForeignKey('entity_attachment.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # Путь к файлу версии на диске. Задаётся при создании, бизнес-логика
    # отвечает за консистентность (файл реально существует на диске).
    disk_path = db.Column(db.String(1024), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=True)
    # Кто и когда сохранил эту версию (кто нажал «Сохранить» в редакторе).
    saved_by = db.Column(
        db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'),
        nullable=True,
    )
    saved_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self, user_name: str | None = None):
        return {
            'id': self.id,
            'attachment_id': self.attachment_id,
            'file_size': self.file_size,
            'saved_by': self.saved_by,
            'saved_by_name': user_name,
            'saved_at': self.saved_at.isoformat() if self.saved_at else None,
        }
