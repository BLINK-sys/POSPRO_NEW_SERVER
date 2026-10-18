"""
Таблица-зеркало импорта из Bitrix24. Служит для:
  - идемпотентности (повторный запуск миграции не создаёт дубли)
  - rollback'а (удаление всех записей созданных миграцией)
  - аудита (кто/когда что импортировал)

Один ряд = одна связка «сущность в Б24 → сущность в PosPro».
"""

from datetime import datetime
from extensions import db


class B24Mirror(db.Model):
    __tablename__ = 'b24_mirror'
    __table_args__ = (
        db.UniqueConstraint('entity_type', 'b24_id', name='uq_b24_mirror'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Тип сущности: 'company', 'contact', 'deal', 'task'.
    entity_type = db.Column(db.String(32), nullable=False, index=True)
    # ID в Б24. Строка т.к. у разных сущностей разный тип (у task — int,
    # у crm.* тоже int, но держим string для гибкости).
    b24_id = db.Column(db.String(64), nullable=False)
    # Созданная/обновлённая сущность в нашей БД.
    pospro_id = db.Column(db.Integer, nullable=False)
    # Какая конкретно миграция создала запись (для возможности rollback
    # по batch'у). Пока одно значение 'initial', но резерв на будущее.
    migration_tag = db.Column(db.String(32), nullable=False, default='initial',
                              server_default=db.text("'initial'"))
    imported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
