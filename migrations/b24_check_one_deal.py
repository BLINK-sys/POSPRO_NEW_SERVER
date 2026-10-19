"""
Проверка одной сделки: что сейчас в PosPro, что в B24, что бы сделал rebind.

Запуск:
    python -u -m migrations.b24_check_one_deal --pospro-id 29863
    python -u -m migrations.b24_check_one_deal --b24-id 66861
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.deal import Deal
from models.deal_source import DealSource, DealSourceVariant
from migrations.bitrix24._b24 import call
from migrations.bitrix24.migrate_deals import (
    _resolve_source_and_variant, B24_UF_SOURCE, B24_SOURCE_MAP,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--pospro-id', type=int)
    ap.add_argument('--b24-id', type=str)
    args = ap.parse_args()

    with app.app_context():
        if args.pospro_id:
            row = db.session.execute(text(
                "SELECT b24_id FROM b24_mirror "
                "WHERE entity_type='deal' AND pospro_id=:pid"
            ), {'pid': args.pospro_id}).fetchone()
            if not row:
                print(f'pospro_id={args.pospro_id} не найден в b24_mirror')
                return 1
            b24_id = row.b24_id
            pospro_id = args.pospro_id
        elif args.b24_id:
            b24_id = str(args.b24_id)
            row = db.session.execute(text(
                "SELECT pospro_id FROM b24_mirror "
                "WHERE entity_type='deal' AND b24_id=:bid"
            ), {'bid': b24_id}).fetchone()
            if not row:
                print(f'b24_id={b24_id} не найден в b24_mirror')
                return 1
            pospro_id = row.pospro_id
        else:
            print('Нужен --pospro-id или --b24-id'); return 2

        deal = Deal.query.get(pospro_id)
        print(f'=== PosPro deal#{pospro_id}  b24#{b24_id} ===', flush=True)
        print(f'  name = {deal.name!r}', flush=True)
        print(f'  source_id = {deal.source_id}', flush=True)
        if deal.source_id:
            src = DealSource.query.get(deal.source_id)
            print(f'    → {src.name!r}' if src else '    → (not found)',
                  flush=True)
        print(f'  source_variant_id = {deal.source_variant_id}', flush=True)
        if deal.source_variant_id:
            v = DealSourceVariant.query.get(deal.source_variant_id)
            print(f'    → {v.name!r}' if v else '    → (not found)',
                  flush=True)
        print('', flush=True)

        print('=== B24 raw ===', flush=True)
        r = call('crm.deal.get', {'id': b24_id})
        d = r.get('result') or {}
        print(f'  SOURCE_ID = {d.get("SOURCE_ID")!r}', flush=True)
        print(f'  SOURCE_DESCRIPTION = {(d.get("SOURCE_DESCRIPTION") or "")[:200]!r}',
              flush=True)
        uf = d.get(B24_UF_SOURCE)
        print(f'  {B24_UF_SOURCE} = {uf!r}', flush=True)
        if uf:
            mapped = B24_SOURCE_MAP.get(str(uf))
            print(f'    → maps to {mapped!r}' if mapped
                  else f'    → NOT IN B24_SOURCE_MAP!', flush=True)

        print('', flush=True)
        print('=== Что сделает rebind ===', flush=True)
        src_id, var_id = _resolve_source_and_variant(d)
        print(f'  Target source_id = {src_id}', flush=True)
        if src_id:
            s = DealSource.query.get(src_id)
            print(f'    → {s.name!r}' if s else '    → ???', flush=True)
        print(f'  Target source_variant_id = {var_id}', flush=True)
        if var_id:
            v = DealSourceVariant.query.get(var_id)
            print(f'    → {v.name!r}' if v else '    → ???', flush=True)

        if src_id is None:
            print('', flush=True)
            print('  → UF пустое; rebind НЕ ТРОНЕТ существующий source.',
                  flush=True)
        elif src_id == deal.source_id and var_id == deal.source_variant_id:
            print('', flush=True)
            print('  → Уже совпадает — rebind не менял бы.', flush=True)
        else:
            print('', flush=True)
            print(f'  → Было бы изменение: '
                  f'{deal.source_id}/{deal.source_variant_id} → {src_id}/{var_id}',
                  flush=True)

        db.session.rollback()  # не сохраняем get-or-create из _resolve
    return 0


if __name__ == '__main__':
    sys.exit(main())
