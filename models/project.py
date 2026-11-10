"""
Проект — верхнеуровневый контейнер для задач.

Пример: «Запуск нового филиала», «Внутренние процессы», «Маркетинг Q4».
Задача может быть привязана либо к сделке (`Task.deal_id`), либо к
проекту (`Task.project_id`), либо ни к чему. Оба поля не взаимоисключены
на уровне БД (можно и то, и то) — контроль на UI: юзер выбирает один
слот в пикере.

У проекта:
- `status` — active/archived. Архивный остаётся в системе, но прячется
  из активного списка.
- `owner_id` — владелец (как и исполнитель у задачи: «отвечает за всё»).
- `project_member` — участники (member/observer).
- `project_stage` — колонки собственного канбана.

Удаление проекта ставит `task.project_id = NULL` (задачи не удаляются).
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

    # Статус: 'active' | 'archived'. Архивный не рендерится в списке
    # активных проектов по умолчанию.
    status = db.Column(
        db.String(16), nullable=False, default='active',
        server_default=db.text("'active'"),
    )
    owner_id = db.Column(
        db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'),
        nullable=True,
    )

    created_by = db.Column(db.Integer, db.ForeignKey('system_users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'description': self.description,
            'status': self.status,
            'owner_id': self.owner_id,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# 5 глобальных статусов задачи, допустимые для mapping'а колонки канбана.
PROJECT_STAGE_STATUS_VALUES = (
    'pending',
    'in_progress',
    'waiting_check',
    'done',
    'paused',
)


class ProjectStage(db.Model):
    """
    Колонка канбана проекта. У каждого проекта свой набор. Привязана к
    одному из 5 глобальных статусов задачи — при переносе задачи
    в эту колонку автоматически меняется и глобальный статус.
    """
    __tablename__ = 'project_stage'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    color = db.Column(
        db.String(9), nullable=False, default='#94a3b8',
        server_default=db.text("'#94a3b8'"),
    )
    sort_order = db.Column(
        db.Integer, nullable=False, default=0,
        server_default=db.text('0'),
    )
    # 'pending' | 'in_progress' | 'waiting_check' | 'done' | 'paused'
    maps_to_status = db.Column(
        db.String(16), nullable=False, default='in_progress',
        server_default=db.text("'in_progress'"),
    )
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False,
        server_default=db.text('NOW()'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'color': self.color,
            'sort_order': self.sort_order,
            'maps_to_status': self.maps_to_status,
        }


class ProjectMember(db.Model):
    """
    Участник проекта. Роли:
    - owner    — может всё внутри проекта + настройки (один на проект
                 обычно, но на уровне БД не ограничено — удобно если
                 нужно передать владение).
    - member   — работает с задачами, видит канбан.
    - observer — только чтение.
    Доступ ко всему разделу `/admin/projects` даёт глобальный флаг
    `can_manage_projects`.
    """
    __tablename__ = 'project_member'
    __table_args__ = (
        db.UniqueConstraint('project_id', 'user_id', name='uq_project_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey('system_users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    role = db.Column(
        db.String(16), nullable=False, default='member',
        server_default=db.text("'member'"),
    )
    added_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False,
        server_default=db.text('NOW()'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'role': self.role,
            'added_at': self.added_at.isoformat() if self.added_at else None,
        }
