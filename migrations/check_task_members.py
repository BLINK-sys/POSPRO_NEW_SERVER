"""
Readonly: сколько TaskMember заведено на задачах, разбивка по роли и
сколько задач вообще имеют хоть одного member'а. Нужно убедиться что
migrate_tasks.py реально закатил ACCOMPLICES/AUDITORS из B24.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


def main() -> int:
    with app.app_context():
        n_tasks = db.session.execute(text('SELECT COUNT(*) FROM task')).scalar()
        n_members = db.session.execute(text('SELECT COUNT(*) FROM task_member')).scalar()
        n_tasks_with_members = db.session.execute(text(
            'SELECT COUNT(DISTINCT task_id) FROM task_member'
        )).scalar()

        print(f'task всего:                       {n_tasks}', flush=True)
        print(f'task_member всего записей:        {n_members}', flush=True)
        print(f'task c хотя бы 1 member:          {n_tasks_with_members}', flush=True)
        print('', flush=True)

        rows = db.session.execute(text(
            "SELECT role, COUNT(*) FROM task_member GROUP BY role ORDER BY 1"
        )).fetchall()
        print('--- по ролям ---', flush=True)
        for role, cnt in rows:
            print(f'  {role!r:<14} {cnt}', flush=True)
        print('', flush=True)

        # 3 примера задач с members для глазного sanity-check
        print('--- 3 примера с members ---', flush=True)
        samples = db.session.execute(text("""
            SELECT t.id, t.title,
                   (SELECT COUNT(*) FROM task_member WHERE task_id=t.id) AS n
              FROM task t
             WHERE EXISTS(SELECT 1 FROM task_member WHERE task_id=t.id)
             ORDER BY t.id DESC
             LIMIT 3
        """)).fetchall()
        for r in samples:
            print(f'  task#{r.id} ({r.n} members): {r.title!r}', flush=True)
            mem = db.session.execute(text("""
                SELECT tm.user_id, tm.role, u.full_name
                  FROM task_member tm JOIN system_users u ON u.id = tm.user_id
                 WHERE tm.task_id = :tid
            """), {'tid': r.id}).fetchall()
            for m in mem:
                print(f'      {m.role:<10} #{m.user_id} {m.full_name!r}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
