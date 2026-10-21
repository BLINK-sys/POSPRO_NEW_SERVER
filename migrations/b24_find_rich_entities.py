"""
Readonly: ищет в B24 сделку и задачу с комментариями и файлами, печатает
примеры структуры данных для миграции.

Логика:
  1. Для сделок — пробегает по последним 200 (b24_mirror) и зовёт
     crm.timeline.comment.list(deal) + crm.deal.get.UF-file-полям, считает.
     Берёт первую с comments>0 И files>0 (или просто с max comments).
  2. Для задач — то же через task.commentitem.getlist + UF_TASK_WEBDAV_FILES.
  3. Печатает по 1-2 коммента и 1-2 файла для выбранных.

Запуск:
    python -u -m migrations.b24_find_rich_entities
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from migrations.bitrix24._b24 import call


def _dump(label: str, obj, cut: int = 3000):
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
    with app.app_context():
        # ----- Все file-UF поля сделки/задачи -----
        r = _safe('crm.deal.userfield.list', {'filter[USER_TYPE_ID]': 'file'})
        deal_file_fields = [f.get('FIELD_NAME') for f in (r.get('result') or [])]
        print(f'file-UF полей сделки: {len(deal_file_fields)}', flush=True)
        print(f'  {deal_file_fields}', flush=True)

        # ----- Ищем RICH сделку -----
        deal_rows = db.session.execute(text("""
            SELECT b24_id FROM b24_mirror
             WHERE entity_type='deal'
             ORDER BY CAST(b24_id AS INTEGER) DESC
             LIMIT 200
        """)).fetchall()
        print(f'\nсканирую {len(deal_rows)} последних сделок на comments+files…',
              flush=True)

        best_deal = None  # (b24_id, comments, has_files)
        for i, row in enumerate(deal_rows):
            b24_id = row.b24_id
            # Комменты
            tr = _safe('crm.timeline.comment.list', {
                'order[ID]': 'DESC',
                'filter[ENTITY_ID]': b24_id,
                'filter[ENTITY_TYPE]': 'deal',
                'start': 0,
            })
            comments_total = tr.get('total') if isinstance(tr, dict) else 0
            if not comments_total:
                continue
            # Файлы — проверяем deal.get
            dr = _safe('crm.deal.get', {'id': b24_id})
            dres = dr.get('result') if isinstance(dr, dict) else {}
            files_cnt = 0
            if isinstance(dres, dict):
                for f in deal_file_fields:
                    v = dres.get(f)
                    if v and v not in ('', '0', 0, []):
                        if isinstance(v, list):
                            files_cnt += len(v)
                        else:
                            files_cnt += 1
            if comments_total >= 1 and files_cnt >= 1:
                best_deal = (b24_id, comments_total, files_cnt)
                break
            if (not best_deal) or comments_total > best_deal[1]:
                best_deal = (b24_id, comments_total, files_cnt)

        if best_deal:
            did, cc, fc = best_deal
            print(f'\n★ BEST deal: b24_id={did}  comments={cc}  files={fc}',
                  flush=True)
            # Полный дамп комментов
            r = _safe('crm.timeline.comment.list', {
                'order[ID]': 'ASC',
                'filter[ENTITY_ID]': did,
                'filter[ENTITY_TYPE]': 'deal',
                'start': 0,
            })
            _dump(f'  comments of deal#{did}',
                  (r.get('result') or [])[:3], 3500)
            # UF-поля
            dr = _safe('crm.deal.get', {'id': did})
            dres = dr.get('result') if isinstance(dr, dict) else {}
            file_vals = {}
            for f in deal_file_fields:
                v = dres.get(f) if isinstance(dres, dict) else None
                if v and v not in ('', '0', 0, []):
                    file_vals[f] = v
            _dump(f'  UF files of deal#{did}', file_vals)

        # ----- Ищем RICH задачу -----
        task_rows = db.session.execute(text("""
            SELECT b24_id FROM b24_mirror
             WHERE entity_type='task'
             ORDER BY CAST(b24_id AS INTEGER) DESC
             LIMIT 200
        """)).fetchall()
        print(f'\nсканирую {len(task_rows)} последних задач на comments+files…',
              flush=True)

        best_task = None
        for i, row in enumerate(task_rows):
            b24_id = row.b24_id
            tr = _safe('task.commentitem.getlist', {
                'TASKID': b24_id,
                'ORDER[ID]': 'ASC',
            })
            comments = tr.get('result') if isinstance(tr, dict) else []
            if not isinstance(comments, list):
                continue
            # Файлы — UF_TASK_WEBDAV_FILES
            dr = _safe('task.item.getdata', {'ID': b24_id})
            dres = dr.get('result') if isinstance(dr, dict) else {}
            webdav = dres.get('UF_TASK_WEBDAV_FILES') if isinstance(dres, dict) else []
            files_cnt = len(webdav) if isinstance(webdav, list) else 0
            if len(comments) >= 1 and files_cnt >= 1:
                best_task = (b24_id, len(comments), files_cnt)
                break
            if (not best_task) or len(comments) > best_task[1]:
                best_task = (b24_id, len(comments), files_cnt)

        if best_task:
            tid, cc, fc = best_task
            print(f'\n★ BEST task: b24_id={tid}  comments={cc}  files={fc}',
                  flush=True)
            tr = _safe('task.commentitem.getlist', {
                'TASKID': tid, 'ORDER[ID]': 'ASC',
            })
            _dump(f'  comments of task#{tid}',
                  (tr.get('result') or [])[:3], 3500)
            dr = _safe('task.item.getdata', {'ID': tid})
            dres = dr.get('result') if isinstance(dr, dict) else {}
            _dump(f'  UF_TASK_WEBDAV_FILES',
                  dres.get('UF_TASK_WEBDAV_FILES') or [])
    return 0


if __name__ == '__main__':
    sys.exit(main())
