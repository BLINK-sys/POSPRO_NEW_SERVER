"""
Одноразовая чистка истории версий attachment'ов для конкретной задачи.

Параметр захардкожен: ищем задачу по частичному совпадению title.
Для найденных задач:
  - находим все entity_attachment с entity_type='task'
  - для каждого удаляем все записи entity_attachment_version +
    физически удаляем файлы .v<id> с диска

Сам attachment НЕ удаляется — только история. Idempotent (если версий
нет — скрипт просто ничего не делает).

Запуск через Render Job:
    python -u -m migrations.clear_attachment_versions_for_task
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from models.task import Task
from models.entity_attachment import EntityAttachment, EntityAttachmentVersion


TASK_TITLE_LIKE = '%Счётчик посетителей%'


def main() -> int:
    tasks = (
        Task.query
        .filter(Task.title.ilike(TASK_TITLE_LIKE))
        .all()
    )
    if not tasks:
        print(f'No tasks match {TASK_TITLE_LIKE}', flush=True)
        return 0

    for t in tasks:
        print(f'Task #{t.id}: {t.title!r}', flush=True)
        attachments = EntityAttachment.query.filter_by(
            entity_type='task', entity_id=t.id,
        ).all()
        if not attachments:
            print('  no attachments', flush=True)
            continue
        for a in attachments:
            versions = EntityAttachmentVersion.query.filter_by(
                attachment_id=a.id,
            ).all()
            print(f'  attachment #{a.id} {a.file_name!r}: {len(versions)} versions', flush=True)
            removed_files = 0
            for v in versions:
                if v.disk_path and os.path.exists(v.disk_path):
                    try:
                        os.remove(v.disk_path)
                        removed_files += 1
                    except OSError as e:
                        print(f'    WARN: cannot remove {v.disk_path}: {e}', flush=True)
                db.session.delete(v)
            print(f'    removed files: {removed_files}', flush=True)
    db.session.commit()
    print('Done.', flush=True)
    return 0


if __name__ == '__main__':
    with app.app_context():
        sys.exit(main())
