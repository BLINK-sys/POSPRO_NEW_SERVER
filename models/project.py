"""
Проект — верхнеуровневый контейнер для задач, не связанных со сделкой.

Пример: «Запуск нового филиала», «Внутренние процессы», «Маркетинг Q4».
Задача может быть привязана либо к сделке (`Task.deal_id`), либо к
проекту (`Task.project_id`), либо ни к чему. Оба поля не взаимоисключены
на уровне БД (можно и то, и то) — контроль на UI: юзер выбирает один
слот в пикере.

Проекты создаются вручную из /admin/projects. Удаление проекта ставит
`task.project_id = NULL` (задачи не удаляются).
"""

from datetime import datetime

from extensions import db


class Project(db.Model):
    __tablename__ = 'project'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    # Цвет для чипа в таблице задач; hex `#RRGGBB`, дефолт — brand yellow.
    color = db.Column(db.String(9), nullable=False, default='#facc15', server_default=db.text("'#facc15'"))
    description = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'description': self.description,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
