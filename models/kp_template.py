from extensions import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB


class KpTemplate(db.Model):
    """
    Шаблон настроек КП. Хранит «фирменный бланк» в формате kpSettings
    (без `kpName` — название принадлежит конкретному КП, а не шаблону).

    Shared-пул на всех системных пользователей: любой admin/system видит
    все шаблоны и может их создавать/редактировать/удалять. Применение
    шаблона = разовое копирование `settings` в текущие kpSettings юзера.
    Сам шаблон при этом не меняется.

    `settings` — JSONB-блоб со структурой:
      columns / columnWidths / columnFontSizes / columnHeaderFontSizes /
      columnAligns / columnHeaderAligns / mergeImageName / managerAlign /
      logos[] / textElements[] / footer / title / footerNote

    Картинки (logos[].serverUrl, footer.elements[type=image].serverUrl)
    хранят оригинальные пути из `/uploads/kp-logos/<authorId>/<filename>`.
    При попытке удалить файл из галереи бэк сначала проверяет ссылки в
    шаблонах через `KpTemplate.file_is_in_use(filename)` — если файл
    упомянут хоть в одном шаблоне, удаление блокируется 409.
    """
    __tablename__ = 'kp_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    settings = db.Column(JSONB, nullable=False, default=dict, server_default='{}')

    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'settings': self.settings or {},
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def file_is_in_use(cls, filename: str) -> int:
        """
        Сколько шаблонов ссылаются на файл `filename` (через `logoFilename`
        в logos[] или footer.elements[]). Шаблонов в системе мало (десятки),
        поэтому проще пройти по всем в Python чем строить JSONB-запрос.
        """
        if not filename:
            return 0
        count = 0
        for tpl in cls.query.all():
            s = tpl.settings or {}
            for slot in (s.get('logos') or []):
                if slot.get('logoFilename') == filename:
                    count += 1
                    break  # одна ссылка от шаблона достаточно
            else:
                for fel in ((s.get('footer') or {}).get('elements') or []):
                    if fel.get('type') == 'image' and fel.get('logoFilename') == filename:
                        count += 1
                        break
        return count
