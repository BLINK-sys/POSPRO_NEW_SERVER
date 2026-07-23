"""
Модели для локального сервера автоматических выгрузок (BIO/Equip).

Архитектура (см. project_integration_worker.md в memory):
- Worker на локалке (DESKTOP-15IPGLJ) читает settings, pull'ит команды,
  запускает миграции subprocess'ом, шлёт heartbeat со статусом.
- Прод хранит settings + историю runs + очередь команд, отдаёт админке
  для отображения карточек и детальных страниц с polling.
"""

from extensions import db
from datetime import datetime


# Типы интеграций. Хардкод — их всего две, вложенных enum-таблицы делать нет смысла.
INTEGRATION_TYPES = ('bio', 'equip')

# Режимы расписания:
# - weekly:   {"days": ["mon","fri"], "time": "03:00"}  — выбранные дни недели
# - interval: {"days": 14, "time": "04:00", "anchor": "2026-07-24"}  — каждые N дней
SCHEDULE_MODES = ('weekly', 'interval')

# Статусы run'ов
RUN_STATUSES = ('running', 'success', 'failed', 'cancelled')

# Фазы run'ов (для UI прогресса)
RUN_PHASES = (
    'starting',          # только запустился
    'fetch_categories',  # этап 1 — сбор данных: категории
    'fetch_brands',      # этап 1 — сбор данных: бренды
    'fetch_products',    # этап 1 — сбор данных: товары
    'upload_categories', # этап 2 — выгрузка в магазин: категории
    'upload_brands',     # этап 2 — выгрузка в магазин: бренды
    'upload_products',   # этап 2 — выгрузка в магазин: товары
    'done',              # финиш
)


class IntegrationSettings(db.Model):
    """Одна запись на каждый тип интеграции (bio, equip)."""
    __tablename__ = 'integration_settings'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False, unique=True)  # 'bio'/'equip'
    enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    # Режим расписания + произвольные данные под режим (см. SCHEDULE_MODES выше).
    schedule_mode = db.Column(db.String(20), nullable=False, default='weekly')
    schedule_data = db.Column(db.JSON, nullable=False, default=dict, server_default=db.text("'{}'::jsonb"))
    # Heartbeat от воркера — определяет «онлайн ли локальный сервер».
    # Если last_heartbeat_at старше 2 минут → на карточке показываем «оффлайн».
    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'enabled': bool(self.enabled),
            'schedule_mode': self.schedule_mode,
            'schedule_data': self.schedule_data,
            'last_heartbeat_at': self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class IntegrationRun(db.Model):
    """История выгрузок. По одной записи на каждый запуск (scheduled/manual)."""
    __tablename__ = 'integration_run'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False, index=True)
    trigger = db.Column(db.String(20), nullable=False)  # 'scheduled'/'manual'
    triggered_by = db.Column(db.String(255), nullable=True)  # email админа для manual

    started_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='running', index=True)
    phase = db.Column(db.String(50), nullable=True)
    # {categories_done, categories_total, products_done, products_total, ...}
    progress = db.Column(db.JSON, nullable=True)
    error = db.Column(db.Text, nullable=True)
    # Последние ~50 строк лога, для UI. Полный лог остаётся на локалке в файле.
    log_excerpt = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'trigger': self.trigger,
            'triggered_by': self.triggered_by,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'status': self.status,
            'phase': self.phase,
            'progress': self.progress,
            'error': self.error,
            'log_excerpt': self.log_excerpt,
        }


class IntegrationCommand(db.Model):
    """
    Очередь команд от админки к воркеру. Воркер pull'ит через
    /internal/integrations/<type>/pending-command и помечает consumed_at.

    Пока команда одна — 'run_now'. Дальше можно расширить: 'cancel', 'reload_settings'.
    """
    __tablename__ = 'integration_command'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False, index=True)
    command = db.Column(db.String(30), nullable=False)  # 'run_now'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(255), nullable=True)  # email админа
    consumed_at = db.Column(db.DateTime, nullable=True)    # когда воркер подхватил

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'command': self.command,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
            'consumed_at': self.consumed_at.isoformat() if self.consumed_at else None,
        }
