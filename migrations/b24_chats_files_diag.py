"""
Readonly diag: как в B24 устроены комментарии и файлы для одной сделки
и одной задачи. Выводит структуру ответа API, нужную для построения
миграции чатов/файлов.

Запуск:
    python -u -m migrations.b24_chats_files_diag \\
        --deal-b24 <ID> --task-b24 <ID>
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from migrations.bitrix24._b24 import call


def _dump(label: str, obj, cut: int = 3500):
    print(f'\n--- {label} ---', flush=True)
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(s) > cut:
        s = s[:cut] + f'\n…[{len(s)} bytes]'
    print(s, flush=True)


def _safe(method, params=None):
    try:
        return call(method, params or {})
    except Exception as e:
        return {'__error__': str(e)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--deal-b24', type=str, default=None)
    p.add_argument('--task-b24', type=str, default=None)
    args = p.parse_args()

    with app.app_context():
        # Fallback: взять самую свежую сделку и задачу из mirror.
        deal_b24 = args.deal_b24
        if not deal_b24:
            row = db.session.execute(text("""
                SELECT b24_id FROM b24_mirror
                 WHERE entity_type='deal'
                 ORDER BY CAST(b24_id AS INTEGER) DESC LIMIT 1
            """)).fetchone()
            deal_b24 = row.b24_id if row else None
        task_b24 = args.task_b24
        if not task_b24:
            row = db.session.execute(text("""
                SELECT b24_id FROM b24_mirror
                 WHERE entity_type='task'
                 ORDER BY CAST(b24_id AS INTEGER) DESC LIMIT 1
            """)).fetchone()
            task_b24 = row.b24_id if row else None

        print(f'=== deal_b24={deal_b24}  task_b24={task_b24}', flush=True)

        # --- СДЕЛКА ---
        if deal_b24:
            # Timeline comments — обычно именно эти комменты видно в карточке сделки.
            r = _safe('crm.timeline.comment.list', {
                'order': {'ID': 'DESC'},
                'filter': {'ENTITY_ID': deal_b24, 'ENTITY_TYPE': 'deal'},
                'start': 0,
            })
            _dump(f'crm.timeline.comment.list deal#{deal_b24}', r)

            # UF-поля сделки с типом file (DEPRECATED в UI уже нет такого, но
            # могут остаться старые записи). Нам нужны ВСЕ UF type=file.
            r = _safe('crm.deal.userfield.list', {'filter': {'USER_TYPE_ID': 'file'}})
            _dump('crm.deal.userfield.list filter type=file', r)

            # Сама сделка — чтобы увидеть что в UF-file полях у неё лежит.
            r = _safe('crm.deal.get', {'id': deal_b24})
            res = r.get('result') if isinstance(r, dict) else r
            # Вытащим только ключи с UF и файлового вида.
            if isinstance(res, dict):
                uf_file = {k: v for k, v in res.items()
                           if k.startswith('UF_') and v and v not in ('0', 0)}
                _dump(f'crm.deal.get({deal_b24}) UF-поля (не пустые)', uf_file, 2500)

        # --- ЗАДАЧА ---
        if task_b24:
            # Комментарии задачи — legacy, но работает.
            r = _safe('task.commentitem.getlist', {
                'TASKID': task_b24,
                'ORDER': {'ID': 'ASC'},
            })
            _dump(f'task.commentitem.getlist task#{task_b24}', r)

            # Файлы задачи приходят в task.item.getdata в UF_TASK_WEBDAV_FILES.
            # Уже видели в предыдущем diag, но покажем ещё раз для контекста.
            r = _safe('task.item.getdata', {'ID': task_b24})
            res = r.get('result') if isinstance(r, dict) else r
            if isinstance(res, dict):
                webdav = res.get('UF_TASK_WEBDAV_FILES')
                _dump(f'task#{task_b24}.UF_TASK_WEBDAV_FILES', webdav)

            # Отдельно: как качать файл по ATTACHMENT_ID из disk? Для задачи
            # DOWNLOAD_URL — абсолютный путь /bitrix/tools/disk/uf.php?...
            # Нам нужно просто GET на https://pospro24.bitrix24.kz{DOWNLOAD_URL}.
            # Но auth=aplogin/ap — это уже встроены в URL (web-hook token).
            # Если юзера нет в B24 — доступа тоже может не быть.
    return 0


if __name__ == '__main__':
    sys.exit(main())
