"""
Откат миграции из Б24 — удаляет импортированные сущности по типу
(deal / contact / company / task) используя трекинг в b24_mirror.

CLI:
  python -u -m migrations.bitrix24.rollback --entity deal
  python -u -m migrations.bitrix24.rollback --entity deal --limit 10
  python -u -m migrations.bitrix24.rollback --entity all   # всё что импортировано

Порядок удаления (чтобы FK не ловили):
  task → deal → contact → company
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db

from models.b24_mirror import B24Mirror
from models.deal import Deal
from models.task import Task
from models.kp_client import KpClient
from models.kp_company import KpCompany


MODEL_BY_TYPE = {
    'task': Task,
    'deal': Deal,
    'contact': KpClient,
    'company': KpCompany,
}

ORDER = ['task', 'deal', 'contact', 'company']


def rollback_type(entity_type: str, limit: int) -> int:
    Model = MODEL_BY_TYPE[entity_type]
    q = B24Mirror.query.filter_by(entity_type=entity_type)
    if limit:
        q = q.limit(limit)
    rows = q.all()
    print(f'  → {entity_type}: {len(rows)} to delete', flush=True)
    n = 0
    for r in rows:
        obj = Model.query.get(r.pospro_id)
        if obj:
            db.session.delete(obj)
        db.session.delete(r)
        n += 1
        if n % 100 == 0:
            db.session.commit()
    db.session.commit()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entity', required=True,
                    choices=['task', 'deal', 'contact', 'company', 'all'])
    ap.add_argument('--limit', type=int, default=0,
                    help='удалить только N последних (0 = все)')
    args = ap.parse_args()

    print(f'=== rollback entity={args.entity} limit={args.limit or "ALL"} ===',
          flush=True)
    with app.app_context():
        if args.entity == 'all':
            for t in ORDER:
                rollback_type(t, args.limit)
        else:
            rollback_type(args.entity, args.limit)
    print('✅ done', flush=True)


if __name__ == '__main__':
    main()
