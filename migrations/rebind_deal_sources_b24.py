"""
Пересчёт source_id + source_variant_id для сделок, пришедших из B24.

Проходит по всем записям b24_mirror(entity_type='deal'), для каждой
запрашивает актуальные значения UF_CRM_1694591054634 («Источник...»)
и SOURCE_DESCRIPTION из B24, вычисляет (source_id, source_variant_id)
через миграционный хелпер _resolve_source_and_variant и обновляет
deal в PosPro.

Dry-run по умолчанию. Запуск батчами по 50 — равно B24-странице и даёт
короткие транзакции с частыми коммитами.

Используется ОДИН РАЗ после merge/migrate — чтобы 29к старых сделок
получили правильный источник вместо старого (который брался из
стандартного SOURCE_ID = 'CALL'/'WEB'/'IM_KASPI').

Запуск:
    python -u -m migrations.rebind_deal_sources_b24
    python -u -m migrations.rebind_deal_sources_b24 --apply
    python -u -m migrations.rebind_deal_sources_b24 --apply --limit 100
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.deal import Deal
from migrations.bitrix24._b24 import call
from migrations.bitrix24.migrate_deals import (
    _resolve_source_and_variant, B24_UF_SOURCE,
)


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true',
                   help='Применить изменения (без флага — dry-run)')
    p.add_argument('--limit', type=int, default=0,
                   help='Остановиться после N обработанных (для тестов)')
    p.add_argument('--batch', type=int, default=50,
                   help='Размер B24-страницы (default 50)')
    return p.parse_args()


def _fetch_batch(b24_ids: list[str]) -> dict:
    """Вытаскивает нужные поля для списка B24 deal-id одним запросом."""
    if not b24_ids:
        return {}
    r = call('crm.deal.list', {
        'select[]': ['ID', 'SOURCE_DESCRIPTION', B24_UF_SOURCE],
        'filter[ID]': b24_ids,
        'start': 0,
    })
    out = {}
    for d in r.get('result') or []:
        out[str(d.get('ID'))] = d
    return out


def main() -> int:
    args = _parse_args()

    with app.app_context():
        rows = db.session.execute(text(
            "SELECT b24_id, pospro_id FROM b24_mirror "
            "WHERE entity_type = 'deal' ORDER BY CAST(b24_id AS INTEGER)"
        )).fetchall()
        total = len(rows)
        print(f'=== rebind_deal_sources_b24  mode={"APPLY" if args.apply else "DRY-RUN"} '
              f'items={total}  batch={args.batch} ===', flush=True)
        if args.limit:
            rows = rows[:args.limit]

        n_proc = n_changed = n_variants_new = n_sources_new = 0
        changes_sample: list[str] = []

        for i in range(0, len(rows), args.batch):
            chunk = rows[i:i + args.batch]
            b24_ids = [str(r.b24_id) for r in chunk]
            pid_by_b24 = {str(r.b24_id): r.pospro_id for r in chunk}

            try:
                data_by_id = _fetch_batch(b24_ids)
            except Exception as e:
                print(f'  B24 batch failed @{i}: {e}', flush=True)
                continue

            for b24_id in b24_ids:
                n_proc += 1
                b24_data = data_by_id.get(b24_id)
                if not b24_data:
                    continue
                pospro_id = pid_by_b24[b24_id]
                deal = Deal.query.get(pospro_id)
                if not deal:
                    continue

                src_before = deal.source_id
                var_before = deal.source_variant_id

                # resolve добавляет новые DealSource/DealSourceVariant если
                # нужно — считаем сколько создалось для отчёта.
                before_sources = db.session.query(text("1")).from_statement(
                    text("SELECT 1")
                )  # noop — используем прямой count ниже
                src_id, var_id = _resolve_source_and_variant(b24_data)

                if src_id == src_before and var_id == var_before:
                    continue

                if args.apply:
                    deal.source_id = src_id
                    deal.source_variant_id = var_id
                n_changed += 1
                if len(changes_sample) < 15:
                    changes_sample.append(
                        f'  deal#{pospro_id} b24#{b24_id}: '
                        f'src {src_before} → {src_id}  '
                        f'variant {var_before} → {var_id}'
                    )

            if args.apply:
                db.session.commit()

            if (i // args.batch) % 10 == 0:
                print(f'  …processed {n_proc}/{len(rows)}  changed={n_changed}',
                      flush=True)

        if args.apply:
            db.session.commit()

        print('', flush=True)
        print(f'=== TOTALS ===', flush=True)
        print(f'  processed: {n_proc}', flush=True)
        print(f'  changed:   {n_changed}', flush=True)
        print('', flush=True)
        print('  sample changes (first 15):', flush=True)
        for s in changes_sample:
            print(s, flush=True)
        if not args.apply:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
