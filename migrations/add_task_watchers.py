"""
Разовое добавление задачи в «Отслеживаемые» для списка юзеров.

Поиск задачи — по подстроке в title. Поиск юзеров — по подстроке в
full_name/first_name/last_name/email. Dry-run по умолчанию.

Запуск:
    python -u -m migrations.add_task_watchers \\
        --task "Счётчик посетителей" \\
        --user "Данияр" --user "Бахытжан"
    python -u -m migrations.add_task_watchers ... --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db

from models.task import Task, TaskWatcher
from models.systemuser import SystemUser


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task', help='Подстрока title задачи')
    p.add_argument('--task-id', type=int, help='ID задачи (альтернатива --task; '
                   'нужно при mojibake кириллицы на Render Job)')
    p.add_argument('--user', action='append', default=[],
                   help='Подстрока для поиска юзера (можно несколько раз)')
    p.add_argument('--user-id', action='append', default=[], type=int,
                   help='ID юзера (альтернатива --user; можно несколько раз)')
    p.add_argument('--list', action='store_true',
                   help='Diag-режим: распечатать --list-limit последних '
                        'задач и всех юзеров (id/name/email), чтобы найти id.')
    p.add_argument('--list-limit', type=int, default=50)
    p.add_argument('--list-grep', default=None,
                   help='Фильтр заголовков через SQL ILIKE %...%. '
                        'Передавай latin-подстроку или часть эмоджи — '
                        'кириллица в argv на Render ломается.')
    p.add_argument('--apply', action='store_true')
    return p.parse_args()


def _find_user(q: str) -> SystemUser | None:
    ql = f'%{q.lower()}%'
    users = SystemUser.query.filter(
        db.or_(
            db.func.lower(SystemUser.full_name).like(ql),
            db.func.lower(SystemUser.email).like(ql),
        )
    ).all()
    if len(users) == 1:
        return users[0]
    if len(users) == 0:
        print(f'  ✗ user {q!r}: не найден', flush=True)
        return None
    print(f'  ✗ user {q!r}: найдено {len(users)} — уточни:', flush=True)
    for u in users[:10]:
        print(f'      id={u.id}  {u.full_name!r}  {u.email!r}', flush=True)
    return None


def _find_task(q: str) -> Task | None:
    ql = f'%{q.lower()}%'
    tasks = Task.query.filter(
        db.func.lower(Task.title).like(ql),
    ).order_by(Task.id.desc()).all()
    if len(tasks) == 1:
        return tasks[0]
    if len(tasks) == 0:
        print(f'  ✗ task {q!r}: не найден', flush=True)
        return None
    print(f'  ✗ task {q!r}: найдено {len(tasks)} — уточни:', flush=True)
    for t in tasks[:10]:
        print(f'      id={t.id}  {t.title!r}', flush=True)
    return None


def main() -> int:
    args = _parse_args()
    with app.app_context():
        if args.list:
            print('=== LIST MODE ===', flush=True)
            print(f'--- {args.list_limit} последних задач ---', flush=True)
            q = Task.query
            if args.list_grep:
                q = q.filter(db.func.lower(Task.title).like(
                    f'%{args.list_grep.lower()}%'))
            for t in q.order_by(Task.id.desc()).limit(args.list_limit):
                print(f'  id={t.id:<5} {t.title!r}', flush=True)
            print('', flush=True)
            print('--- Все юзеры ---', flush=True)
            for u in SystemUser.query.order_by(SystemUser.id).all():
                print(f'  id={u.id:<4} {u.full_name!r:<40} {u.email!r}',
                      flush=True)
            return 0

        print(f'=== add_task_watchers  mode={"APPLY" if args.apply else "DRY-RUN"}',
              flush=True)
        # Задача: по id или по имени.
        task = None
        if args.task_id is not None:
            task = Task.query.get(args.task_id)
            if not task:
                print(f'  ✗ task id={args.task_id}: не найден', flush=True)
                return 1
        elif args.task:
            task = _find_task(args.task)
        else:
            print('  ✗ нужен --task или --task-id (или --list)', flush=True)
            return 1
        if not task:
            return 1
        print(f'  task: id={task.id}  title={task.title!r}', flush=True)

        # Юзеры: по id'шкам + по подстрокам.
        users: list[SystemUser] = []
        for uid in args.user_id:
            u = SystemUser.query.get(uid)
            if not u:
                print(f'  ✗ user id={uid}: не найден', flush=True)
                return 1
            users.append(u)
        for q in args.user:
            u = _find_user(q)
            if not u:
                return 1
            users.append(u)
        if not users:
            print('  ✗ нужен хотя бы один --user или --user-id', flush=True)
            return 1
        for u in users:
            print(f'  user: id={u.id}  {u.full_name!r}  {u.email!r}', flush=True)
        print('', flush=True)

        n_added = n_already = 0
        for u in users:
            existing = TaskWatcher.query.filter_by(
                user_id=u.id, task_id=task.id,
            ).first()
            if existing:
                n_already += 1
                print(f'  = {u.full_name!r} уже отслеживает', flush=True)
                continue
            n_added += 1
            print(f'  + {u.full_name!r} будет добавлен', flush=True)
            if args.apply:
                db.session.add(TaskWatcher(user_id=u.id, task_id=task.id))

        if args.apply and n_added:
            db.session.commit()
            print('', flush=True)
            print(f'OK, добавлено {n_added}, уже было {n_already}.', flush=True)
        elif not args.apply:
            print('', flush=True)
            print(f'DRY-RUN: будет добавлено {n_added}, уже есть {n_already}. '
                  '--apply для реального.', flush=True)
        else:
            print('Все уже отслеживают.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
