"""
Пост-обработка миграции: заполнение `deal.source_id` для сделок,
импортированных из Б24 (их `deal.source_ref_type='bitrix24'`).

Что делает:
  1. Выгружает `crm.status.list?filter[ENTITY_ID]=SOURCE` — все источники
     Б24 (CALL, EMAIL, WEB, OTHER + кастомные типа INSTAGRAM, OLX и т.п.).
  2. Fuzzy-mapping на наши `DealSource` по name (ё→е, lower, strip).
     Для unmatched — создаёт новый DealSource (1-в-1 как в Б24, цвет
     нейтрально-серый — админ потом разметит).
  3. Пробегает crm.deal.list пачками с полями `[ID, SOURCE_ID]` и
     обновляет `Deal.source_id` через b24_mirror.

Идемпотентно: при повторном запуске новые source'ы не создадутся
(матчится по name), сделки с уже заполненным source_id пропускаются.

Запуск:
  python -u -m migrations.bitrix24.enrich_sources
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db
from sqlalchemy import func

from models.deal import Deal
from models.deal_source import DealSource

from migrations.bitrix24._b24 import call as b24_call, iter_list
from migrations.bitrix24._utils import mirror_get


def _norm(s: str) -> str:
    return ''.join((s or '').strip().lower().replace('ё', 'е').split())


def fetch_b24_sources() -> list[dict]:
    """
    crm.status.list возвращает все статусы — фильтруем по ENTITY_ID=SOURCE.
    Там и штатные (CALL/EMAIL/WEB), и кастомные.
    """
    out = b24_call('crm.status.list', {'filter[ENTITY_ID]': 'SOURCE'})
    return out.get('result') or []


def ensure_sources_mapping() -> dict[str, int]:
    """
    Строит map b24_source_code → pospro DealSource.id. Создаёт недостающих.
    """
    b24 = fetch_b24_sources()
    print(f'→ got {len(b24)} B24 sources', flush=True)

    existing = {s.id: s for s in DealSource.query.all()}
    by_norm_name = {_norm(s.name): s for s in existing.values()}

    mapping: dict[str, int] = {}
    created = 0
    for s in b24:
        code = s.get('STATUS_ID')  # 'CALL', 'OLX_WEBFORM' и т.п.
        name = (s.get('NAME') or '').strip()
        if not code or not name:
            continue
        hit = by_norm_name.get(_norm(name))
        if hit:
            mapping[code] = hit.id
            continue
        # Создаём недостающий
        max_order = db.session.query(
            func.coalesce(func.max(DealSource.sort_order), 0)
        ).scalar() or 0
        ds = DealSource(
            name=name[:128],
            color='#94a3b8',
            is_active=True,
            sort_order=int(max_order) + 10,
        )
        db.session.add(ds)
        db.session.flush()
        by_norm_name[_norm(name)] = ds
        mapping[code] = ds.id
        created += 1
        print(f'  + source {code!r} → #{ds.id} ({name!r})', flush=True)
    db.session.commit()
    print(f'→ sources created: {created}', flush=True)
    return mapping


def enrich_deals(source_map: dict[str, int]) -> None:
    """
    Проходит все сделки Б24 вторым заходом с полями ID+SOURCE_ID
    и обновляет наши deal.source_id там где он ещё null.
    """
    print('→ enriching deals.source_id…', flush=True)
    updated = 0
    skipped_already = 0
    skipped_no_mapping = 0
    skipped_not_imported = 0
    n = 0
    for d in iter_list('crm.deal.list', {
        'select[]': ['ID', 'SOURCE_ID'],
        'order[ID]': 'ASC',
    }):
        n += 1
        b24_id = d.get('ID')
        src_code = d.get('SOURCE_ID')
        if not src_code:
            continue
        pospro_source_id = source_map.get(src_code)
        if not pospro_source_id:
            skipped_no_mapping += 1
            continue
        pospro_deal_id = mirror_get('deal', b24_id)
        if not pospro_deal_id:
            skipped_not_imported += 1
            continue
        # Проверим не стоит ли уже этот source — чтобы не делать лишний UPDATE
        d_obj = Deal.query.get(pospro_deal_id)
        if not d_obj:
            continue
        if d_obj.source_id == pospro_source_id:
            skipped_already += 1
            continue
        d_obj.source_id = pospro_source_id
        updated += 1
        if n % 500 == 0:
            db.session.commit()
            print(f'  [{n:5d}] updated so far: {updated}', flush=True)
    db.session.commit()
    print(f'\n=== TOTALS ===', flush=True)
    print(f'  processed: {n}', flush=True)
    print(f'  updated:   {updated}', flush=True)
    print(f'  already:   {skipped_already}', flush=True)
    print(f'  no src map:{skipped_no_mapping}', flush=True)
    print(f'  not import:{skipped_not_imported}', flush=True)


def main():
    print('=== enrich_sources ===', flush=True)
    with app.app_context():
        src_map = ensure_sources_mapping()
        print(f'→ source_map has {len(src_map)} entries', flush=True)
        enrich_deals(src_map)
    print('\n✅ done', flush=True)


if __name__ == '__main__':
    main()
