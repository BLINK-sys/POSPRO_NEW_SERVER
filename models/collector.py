"""
Модели для сервиса сбора данных 2GIS.

Отличия от `integration.py` (BIO/Equip):
- Задачи per-user (owner_id), а не глобальные интеграции.
- Расписания нет — только on-demand запуск через админку.
- Свой heartbeat (`CollectorWorker`) — воркер отдельный от BIO/Equip:
  живёт под logon-сессией Алины на резервном ПК (для не-headless Chrome).
- Файлы .xlsx хранятся на локалке; прод только знает пути и проксирует
  скачивание через X-Integration-Key.

FIFO очередь — на стороне воркера (queue.Queue), в БД её проекция —
task.status = 'queued'. Так же как сделали для BIO/Equip после инцидента,
когда команда consumed_at сразу и UI не видел, что задача поставлена.
"""

from extensions import db
from datetime import datetime


# Статусы задачи. 'queued' — воркер получил и поставил в свою очередь.
TASK_STATUSES = ('queued', 'running', 'success', 'failed', 'cancelled')

# Команды в очереди воркера.
TASK_COMMANDS = ('run_now', 'cancel')

# Статусы файла (одна пара «город × запрос»).
FILE_STATUSES = ('ok', 'failed', 'skipped', 'stopped')

# Формат выходного файла.
FILE_FORMATS = ('xlsx', 'csv', 'json')


class CollectorTask(db.Model):
    """
    Одна задача сбора: декартово произведение cities × queries, ИЛИ
    один готовый URL (тогда cities=[extracted_city], queries=[extracted_query]).
    """
    __tablename__ = 'collector_task'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('system_users.id'), nullable=False, index=True)

    # Вход: либо cities + queries, либо custom_url (парсится на пары).
    cities = db.Column(db.JSON, nullable=False, default=list, server_default=db.text("'[]'::jsonb"))
    queries = db.Column(db.JSON, nullable=False, default=list, server_default=db.text("'[]'::jsonb"))
    custom_url = db.Column(db.Text, nullable=True)

    # Постобработка (соответствует gis2_collector.PostprocessOptions).
    keep_columns = db.Column(db.JSON, nullable=True)  # [] = удалить всё, None = не трогать состав
    drop_other_columns = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    autosize_columns = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    wrap_text = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('false'))
    networks_min_count = db.Column(db.Integer, nullable=True)
    sort_by_name = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('false'))

    # Сборные параметры (обычно дефолтные из либы).
    max_records = db.Column(db.Integer, nullable=True)
    file_format = db.Column(db.String(10), nullable=False, default='xlsx', server_default='xlsx')
    delay_min_ms = db.Column(db.Integer, nullable=False, default=3000, server_default='3000')
    delay_max_ms = db.Column(db.Integer, nullable=False, default=5000, server_default='5000')

    # Прогон и результат.
    status = db.Column(db.String(20), nullable=False, default='queued', index=True, server_default='queued')
    phase = db.Column(db.String(50), nullable=True)
    # {pair_index, pair_total, records, current_city, current_query, ...}
    progress = db.Column(db.JSON, nullable=True)
    # Последние N строк лога от collect() — для UI, полный лог на локалке.
    log_excerpt = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    files = db.relationship('CollectorFile', backref='task', cascade='all, delete-orphan',
                             order_by='CollectorFile.id')

    def _utc(self, dt):
        return (dt.isoformat() + 'Z') if dt else None

    def to_dict(self, include_files=False):
        result = {
            'id': self.id,
            'owner_id': self.owner_id,
            'cities': self.cities or [],
            'queries': self.queries or [],
            'custom_url': self.custom_url,
            'keep_columns': self.keep_columns,
            'drop_other_columns': bool(self.drop_other_columns),
            'autosize_columns': bool(self.autosize_columns),
            'wrap_text': bool(self.wrap_text),
            'networks_min_count': self.networks_min_count,
            'sort_by_name': bool(self.sort_by_name),
            'max_records': self.max_records,
            'file_format': self.file_format,
            'delay_min_ms': self.delay_min_ms,
            'delay_max_ms': self.delay_max_ms,
            'status': self.status,
            'phase': self.phase,
            'progress': self.progress,
            'log_excerpt': self.log_excerpt,
            'error': self.error,
            'created_at': self._utc(self.created_at),
            'started_at': self._utc(self.started_at),
            'finished_at': self._utc(self.finished_at),
        }
        if include_files:
            result['files'] = [f.to_dict() for f in self.files]
        return result


class CollectorFile(db.Model):
    """Один собранный файл — соответствует gis2_collector.CollectedFile."""
    __tablename__ = 'collector_file'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('collector_task.id', ondelete='CASCADE'),
                        nullable=False, index=True)

    city = db.Column(db.String(80), nullable=False)
    city_name = db.Column(db.String(200), nullable=True)
    query = db.Column(db.String(500), nullable=False)
    url = db.Column(db.Text, nullable=False)

    # Относительный путь от collector-outputs-корня на локалке.
    # Абсолютный собирается воркером; прод не знает и не должен знать
    # структуру FS локалки.
    rel_path = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(300), nullable=True)  # для Content-Disposition при скачивании

    rows = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    bytes = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    duration_sec = db.Column(db.Float, nullable=False, default=0, server_default='0')
    status = db.Column(db.String(20), nullable=False, default='failed', server_default='failed')
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def _utc(self, dt):
        return (dt.isoformat() + 'Z') if dt else None

    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'city': self.city,
            'city_name': self.city_name,
            'query': self.query,
            'url': self.url,
            'rel_path': self.rel_path,
            'filename': self.filename,
            'rows': self.rows,
            'bytes': self.bytes,
            'attempts': self.attempts,
            'duration_sec': self.duration_sec,
            'status': self.status,
            'error': self.error,
            'created_at': self._utc(self.created_at),
        }


class CollectorCommand(db.Model):
    """
    Очередь команд от админки к воркеру.
    Аналог IntegrationCommand — воркер поллит /internal/next-task
    и /pending-command.
    """
    __tablename__ = 'collector_command'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('collector_task.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    command = db.Column(db.String(30), nullable=False)  # run_now / cancel
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(255), nullable=True)  # email админа
    consumed_at = db.Column(db.DateTime, nullable=True)

    def _utc(self, dt):
        return (dt.isoformat() + 'Z') if dt else None

    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'command': self.command,
            'created_at': self._utc(self.created_at),
            'created_by': self.created_by,
            'consumed_at': self._utc(self.consumed_at),
        }


class CollectorWorker(db.Model):
    """
    Heartbeat отдельного collector-воркера. Отдельно от IntegrationSettings,
    потому что живёт на другом процессе (Task Scheduler под юзером Алина,
    не Windows Service под LocalSystem) — их состояние независимо.

    Единственная запись, id=1.
    """
    __tablename__ = 'collector_worker'

    id = db.Column(db.Integer, primary_key=True)
    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    # Информационное — что воркер сейчас делает / общая инфа.
    hostname = db.Column(db.String(200), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def _utc(self, dt):
        return (dt.isoformat() + 'Z') if dt else None

    def to_dict(self):
        return {
            'id': self.id,
            'last_heartbeat_at': self._utc(self.last_heartbeat_at),
            'hostname': self.hostname,
            'updated_at': self._utc(self.updated_at),
        }
