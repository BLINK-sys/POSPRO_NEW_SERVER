"""
Миграция сделок Б24 → `Deal`.

Для КАЖДОЙ сделки:
  - По STAGE_ID (с префиксом категории) находим pospro_pipeline+stage через
    b24_meta.mapping.stages.
  - COMPANY_ID → kp_company через b24_mirror('company') (если ещё не
    мигрирована — пропускаем или мигрируем on-the-fly? В MVP пропускаем
    привязку, пишем в note.)
  - CONTACT_ID (primary) + crm.deal.contact.items.get для доп. контактов
    → kp_client через b24_mirror('contact') + создаёт deal_contact записи.
  - responsible_user_id = ASSIGNED_BY_ID через user_map, creator_id = CREATED_BY_ID.
  - amount, currency, name, expected_close_at, source — прямым мэппингом.
  - status: по stage.type (won/lost) ставится автоматом в поле Deal.status.
  - в source_ref_type пишем 'bitrix24', в source_ref_id — ID сделки Б24.

Идемпотентно через b24_mirror('deal').

CLI:
  python -u -m migrations.bitrix24.migrate_deals [--limit N] [--dry-run]
"""

import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db

from models.systemuser import SystemUser
from models.deal import Deal
from models.deal_pipeline import DealStage
from models.deal_source import DealSource, DealSourceVariant
from models.kp_company import DealContact

from migrations.bitrix24._b24 import iter_list, call as b24_call
from migrations.bitrix24._utils import (
    load_mapping, user_pospro_id,
    stage_ids_for_b24, mirror_get, mirror_set,
)


# Основное UF-поле «Источник...» в B24 (enumeration). ID получено через
# diag b24_deal_ufields_diag — см. его вывод. Если в B24 появятся новые
# значения в enum, их просто добавляем в B24_SOURCE_MAP (по id → name,
# name должен точно совпадать с DealSource.name).
B24_UF_SOURCE = 'UF_CRM_1694591054634'
B24_SOURCE_MAP: dict[str, str] = {
    '591':  'Instagram',
    '601':  'OLX (Астана)',
    '593':  'OLX (Регионы)',
    '575':  'Kaspi.kz',
    '597':  'Kaspi звонок',
    '577':  'Satu.kz',
    '585':  'Wildberries.ru',
    '583':  'Forte.kz',
    '587':  'Ozon.ru',
    '589':  'Halykmarket.kz',
    '579':  'Старый клиент',
    '581':  'По рекомендации',
    '599':  '2GIS',
    '603':  'Партнер',
    '611':  'Корпоративный клиент',
    '615':  'Kaspi магазин',
    '617':  'Сайт',
    '1023': 'ОЛХ(Выс чек)',
}


FIELDS = [
    'ID', 'TITLE', 'STAGE_ID', 'CATEGORY_ID',
    'OPPORTUNITY', 'CURRENCY_ID', 'IS_WON', 'IS_RETURN',
    'ASSIGNED_BY_ID', 'CREATED_BY_ID',
    'COMPANY_ID', 'CONTACT_ID',
    'BEGINDATE', 'CLOSEDATE', 'DATE_CREATE', 'DATE_MODIFY',
    'SOURCE_ID', 'SOURCE_DESCRIPTION', 'COMMENTS', 'TYPE_ID',
    B24_UF_SOURCE,
    # UF-поля опросника (heat/city/activity/business_type).
    # См. migrations/migrate_survey_from_b24.py — там же обратный маппинг.
    'UF_CRM_1732275174616',       # heat
    'UF_CRM_1668403860',          # city
    'UF_CRM_1668403913',          # activity
    'UF_CRM_DEAL_1744377549767',  # business_type
]


def _resolve_source_and_variant(d: dict) -> tuple[int | None, int | None]:
    """
    По B24-сделке возвращает (source_id, source_variant_id) для PosPro.

    - source: имя через B24_SOURCE_MAP → get-or-create в DealSource
    - variant: SOURCE_DESCRIPTION целиком (строка) → get-or-create в
      DealSourceVariant под этим родителем. Если description пустое или
      source отсутствует — variant = None.

    Коммитов тут не делаем — caller сам закоммитит в своём цикле.
    """
    enum_id = d.get(B24_UF_SOURCE)
    if enum_id in (None, '', 0, '0'):
        return None, None
    name = B24_SOURCE_MAP.get(str(enum_id))
    if not name:
        return None, None

    src = DealSource.query.filter(
        db.func.lower(DealSource.name) == name.lower(),
    ).first()
    if not src:
        src = DealSource(name=name, is_active=True)
        db.session.add(src)
        db.session.flush()

    descr = (d.get('SOURCE_DESCRIPTION') or '').strip()
    if not descr:
        return src.id, None

    # Обрезаем до 500 символов (размер колонки).
    descr = descr[:500]
    variant = DealSourceVariant.query.filter_by(
        parent_source_id=src.id, name=descr,
    ).first()
    if not variant:
        variant = DealSourceVariant(parent_source_id=src.id, name=descr)
        db.session.add(variant)
        db.session.flush()

    return src.id, variant.id


# ─── Survey (Dictionary) resolver ─────────────────────────────────────────
# Для новых импортов сразу тянем heat/city/activity/business_type из UF-полей
# и мэппим на DictionaryItem.id. Полная таблица enum→name — в
# migrations/migrate_survey_from_b24.py (SURVEYS). Здесь используем
# тот же mapping для get-or-create в Dictionary + DictionaryItem.


def _resolve_survey_values(d: dict) -> dict:
    """
    Из b24-сделки `d` возвращает dict {code: dictionary_item.id} для сохранения
    в Deal.survey_values. Пустые UF-поля пропускаем. Коммит делает caller.
    """
    try:
        from migrations.migrate_survey_from_b24 import SURVEYS
    except Exception:
        return {}
    from models.dictionary import Dictionary, DictionaryItem

    out: dict = {}
    for code, (uf, label, enum) in SURVEYS.items():
        raw = d.get(uf)
        if raw in (None, '', 0, '0'):
            continue
        name = enum.get(str(raw))
        if not name:
            continue
        dict_obj = Dictionary.query.filter_by(code=code).first()
        if not dict_obj:
            dict_obj = Dictionary(code=code, label=label)
            db.session.add(dict_obj)
            db.session.flush()
        item = DictionaryItem.query.filter_by(
            dict_id=dict_obj.id, name=name,
        ).first()
        if not item:
            item = DictionaryItem(dict_id=dict_obj.id, name=name)
            db.session.add(item)
            db.session.flush()
        out[code] = item.id
    return out


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        # Bitrix отдаёт `2026-10-15T10:12:00+03:00` или аналогичное
        return datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except Exception:
        return None


def _deal_primary_contact_id(d: dict) -> str | None:
    """
    Primary контакт сделки берём из CONTACT_ID (в основном ответе
    crm.deal.list) — это 95% кейсов. Доп. контакты в этом MVP миграции
    не тащим: отдельный crm.deal.contact.items.get на каждую сделку
    добавил бы +60k запросов при 29k сделок (= 8+ часов с rate-limit).
    Если потом понадобится — отдельным Job'ом догрузим.
    """
    cid = d.get('CONTACT_ID')
    if cid in (None, '', '0', 0):
        return None
    return str(cid)


def _resolve_stage_status(ps_id: int) -> str:
    """Возвращает deal.status ('open'/'won'/'lost') по типу pospro-стадии."""
    s = DealStage.query.get(ps_id)
    if not s:
        return 'open'
    if s.type == 'won':
        return 'won'
    if s.type == 'lost':
        return 'lost'
    return 'open'


def migrate_one(d: dict, mapping: dict, owner_id: int, dry_run: bool) -> str:
    b24_id = d['ID']
    existing_pid = mirror_get('deal', b24_id)
    if existing_pid:
        return f'skip (already imported → pospro #{existing_pid})'

    name = (d.get('TITLE') or '').strip() or f'B24 deal #{b24_id}'
    stage_b24 = d.get('STAGE_ID')
    # В Б24 для категории 0 STAGE_ID без префикса (NEW, UC_X7..., WON, 1-12).
    # Наш stages mapping хранит ключи так же как они пришли из Б24 (т.е.
    # для cat 0 — без префикса). Проверим две формы.
    stage_resolved = stage_ids_for_b24(mapping, stage_b24)
    if not stage_resolved:
        return f'skip (stage {stage_b24!r} not mapped)'
    pipeline_id, stage_id = stage_resolved

    responsible = user_pospro_id(mapping, d.get('ASSIGNED_BY_ID'), owner_id)
    creator = user_pospro_id(mapping, d.get('CREATED_BY_ID'), owner_id)

    company_b24 = d.get('COMPANY_ID')
    company_pid = (mirror_get('company', company_b24)
                   if company_b24 and company_b24 != '0' else None)

    # Primary контакт сделки (без доп. контактов — см. комментарий в
    # _deal_primary_contact_id).
    primary_contact = None
    pcb24 = _deal_primary_contact_id(d)
    if pcb24:
        pid = mirror_get('contact', pcb24)
        if pid:
            primary_contact = pid
    contact_pospro_ids: list[int] = [primary_contact] if primary_contact else []

    amount = None
    try:
        v = d.get('OPPORTUNITY')
        if v not in (None, '', '0'):
            amount = float(v)
    except Exception:
        pass
    currency = (d.get('CURRENCY_ID') or 'KZT').strip() or 'KZT'
    begindate = _parse_dt(d.get('BEGINDATE') or d.get('DATE_CREATE'))
    closedate = _parse_dt(d.get('CLOSEDATE'))
    comments = (d.get('COMMENTS') or '').strip() or None
    status = _resolve_stage_status(stage_id)
    source_id, source_variant_id = _resolve_source_and_variant(d)
    survey_values = _resolve_survey_values(d)

    if dry_run:
        return (f'[dry-run] would create: {name!r} pipeline={pipeline_id} '
                f'stage={stage_id} status={status} amount={amount} '
                f'company_pid={company_pid} contacts={len(contact_pospro_ids)} '
                f'resp=#{responsible} creator=#{creator} '
                f'source=#{source_id} variant=#{source_variant_id}')

    deal = Deal(
        name=name[:255],
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        status=status,
        amount=amount,
        currency=currency,
        expected_close_at=closedate,
        responsible_user_id=responsible,
        creator_id=creator,
        client_id=primary_contact,
        company_id=company_pid,
        notes=comments,
        source_id=source_id,
        source_variant_id=source_variant_id,
        survey_values=survey_values,
        source_ref_type='bitrix24',
        source_ref_id=str(b24_id),
        created_at=begindate or datetime.utcnow(),
    )
    db.session.add(deal)
    db.session.flush()

    for i, cpid in enumerate(contact_pospro_ids):
        db.session.add(DealContact(
            deal_id=deal.id,
            client_id=cpid,
            is_primary=(i == 0),
        ))

    mirror_set('deal', b24_id, deal.id)
    return (f'created #{deal.id} {name!r} stage={stage_id} '
            f'contacts={len(contact_pospro_ids)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print(f'=== migrate_deals  limit={args.limit or "ALL"}  dry_run={args.dry_run} ===',
          flush=True)

    with app.app_context():
        mapping = load_mapping()
        owner = SystemUser.query.filter_by(is_owner=True).first()
        owner_id = owner.id

        n_total = n_created = n_skipped = n_dedup = 0
        for d in iter_list('crm.deal.list', {
            'select[]': FIELDS,
            'order[ID]': 'ASC',  # детерминированный порядок
        }):
            n_total += 1
            result = migrate_one(d, mapping, owner_id, args.dry_run)
            if result.startswith('skip'):
                n_skipped += 1
            elif 'created' in result or 'would create' in result:
                n_created += 1
            # Логируем первые 20 и каждую 100-ю.
            if n_total <= 30 or n_total % 100 == 0:
                print(f'  [{n_total:5d}] b24#{d["ID"]:>7}  {result}', flush=True)
            if args.limit and n_total >= args.limit:
                break
            if not args.dry_run and n_total % 25 == 0:
                db.session.commit()

        if not args.dry_run:
            db.session.commit()

        print(f'\n=== TOTALS ===', flush=True)
        print(f'  processed: {n_total}', flush=True)
        print(f'  created:   {n_created}', flush=True)
        print(f'  skipped:   {n_skipped}', flush=True)


if __name__ == '__main__':
    main()
