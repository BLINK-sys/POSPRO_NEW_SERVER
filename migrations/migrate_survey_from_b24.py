"""
Миграция «опросника» (Dictionary + survey_values) из UF-полей B24.

Для каждой из 4 UF-энумераций создаёт/дополняет справочник Dictionary и
его items (из diag известны все enum id → name). Затем проходит по
b24_mirror(deal) и для каждой сделки вытаскивает актуальные значения UF,
резолвит в наши DictionaryItem.id и записывает в deal.survey_values.

Dry-run по умолчанию. Батчи по 50 (B24 pagination = одна страница на batch).

B24 UF-поля (из b24_deal_ufields_diag):
  UF_CRM_1732275174616    heat          Теплота клиента (4 значения)
  UF_CRM_1668403860       city          Город (24+ значений)
  UF_CRM_1668403913       activity      Вид деятельности (7 значений)
  UF_CRM_DEAL_1744377549767  business_type  Тип бизнеса (7 значений)

Запуск:
    python -u -m migrations.migrate_survey_from_b24
    python -u -m migrations.migrate_survey_from_b24 --apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text

from models.dictionary import Dictionary, DictionaryItem
from models.deal import Deal
from migrations.bitrix24._b24 import call


# code → (B24 UF-поле, человеческое название, {enum_id_str: value_name})
SURVEYS = {
    'heat': (
        'UF_CRM_1732275174616',
        'Теплота клиента',
        {
            '1007': 'Нецелевой',
            '1009': 'Холодный',
            '1011': 'Теплый',
            '1013': 'Горячий',
        },
    ),
    'city': (
        'UF_CRM_1668403860',
        'Город',
        {
            '571': 'Неизвестен',
            '45':  'Алматы',
            '47':  'Астана',
            '49':  'Шымкент',
            '51':  'Актобе',
            '53':  'Караганда',
            '55':  'Тараз',
            '57':  'Атырау',
            '59':  'Павлодар',
            '61':  'Семей',
            '63':  'Усть-Каменогорск',
            '65':  'Уральск',
            '67':  'Кызылорда',
            '69':  'Костанай',
            '71':  'Петропавловск',
            '73':  'Актау',
            '75':  'Кокшетау',
            '77':  'Талдыкорган',
            '79':  'Жезказган',
            '237': 'Темиртау',
            '239': 'Экибастуз',
            '417': 'Балхаш',
            '669': 'Туркестан',
            '805': 'Атбасар',
            '807': 'Акколь',
            '809': 'Щучинск',
        },
    ),
    'activity': (
        'UF_CRM_1668403913',
        'Вид деятельности',
        {
            '81':  'Строительный',
            '83':  'Продуктовый',
            '85':  'Кофейни/рестораны',
            '87':  'Аптека',
            '89':  'Одежда',
            '91':  'Банные комплексы',
            '123': 'Другое',
        },
    ),
    'business_type': (
        'UF_CRM_DEAL_1744377549767',
        'Тип бизнеса',
        {
            '1027': 'Пекарня',
            '1029': 'Кофейня',
            '1031': 'Ресторан',
            '1033': 'Фаст-фуд',
            '1035': 'Мини-маркет',
            '1037': 'Кафе',
            '1045': 'Партнер',
        },
    ),
}


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--limit', type=int, default=0,
                   help='Остановиться после N обработанных')
    p.add_argument('--batch', type=int, default=50)
    return p.parse_args()


def _seed_dicts(apply_: bool) -> dict:
    """
    Создаёт Dictionary + items если их нет. Возвращает мапу
    {code: {enum_id_str: dict_item.id}} для последующего резолва.
    """
    print('=== seeding dictionaries ===', flush=True)
    out: dict[str, dict[str, int]] = {}
    for code, (uf, label, enum) in SURVEYS.items():
        d = Dictionary.query.filter_by(code=code).first()
        created = False
        if not d:
            if apply_:
                d = Dictionary(code=code, label=label)
                db.session.add(d)
                db.session.flush()
            created = True
        enum_to_item: dict[str, int] = {}
        for order_pos, (eid, name) in enumerate(enum.items()):
            if not apply_:
                enum_to_item[eid] = -1  # placeholder для dry-run
                continue
            it = DictionaryItem.query.filter_by(
                dict_id=d.id, name=name,
            ).first()
            if not it:
                it = DictionaryItem(
                    dict_id=d.id, name=name, order_pos=order_pos,
                )
                db.session.add(it)
                db.session.flush()
            enum_to_item[eid] = it.id
        out[code] = enum_to_item
        status = 'CREATED' if created else 'exists'
        print(f'  {code} ({label}, {uf})  [{status}]  items: {len(enum)}',
              flush=True)
    if apply_:
        db.session.commit()
    return out


def _fetch_batch(b24_ids: list[str]) -> dict:
    """
    Батч-запрос в B24 за всеми 4 UF-полями + ID.
    Используем filter[ID][] (array) — single filter[ID] на Render Job
    даёт только последний id (баг doseq, из прошлой итерации).
    """
    if not b24_ids:
        return {}
    uf_fields = [uf for (uf, _, _) in SURVEYS.values()]
    r = call('crm.deal.list', {
        'select[]': ['ID'] + uf_fields,
        'filter[ID][]': [str(x) for x in b24_ids],
        'start': 0,
    })
    out = {}
    for d in r.get('result') or []:
        out[str(d.get('ID'))] = d
    return out


def main() -> int:
    args = _parse_args()
    with app.app_context():
        enum_maps = _seed_dicts(args.apply)
        print('', flush=True)

        rows = db.session.execute(text(
            "SELECT b24_id, pospro_id FROM b24_mirror "
            "WHERE entity_type = 'deal' ORDER BY CAST(b24_id AS INTEGER)"
        )).fetchall()
        total = len(rows)
        print(f'=== process {total} deals  mode={"APPLY" if args.apply else "DRY-RUN"}',
              flush=True)
        if args.limit:
            rows = rows[:args.limit]

        n_proc = n_changed = 0
        n_values_set = 0

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
                deal = Deal.query.get(pid_by_b24[b24_id])
                if not deal:
                    continue

                before = dict(deal.survey_values or {})
                after = dict(before)
                for code, (uf, _, enum) in SURVEYS.items():
                    raw = b24_data.get(uf)
                    if raw in (None, '', 0, '0'):
                        continue
                    item_id = enum_maps[code].get(str(raw))
                    if not item_id or item_id < 0:
                        # dry-run placeholder или неизвестный enum
                        continue
                    if after.get(code) != item_id:
                        after[code] = item_id
                        n_values_set += 1

                if after != before:
                    n_changed += 1
                    if args.apply:
                        deal.survey_values = after

            if args.apply:
                db.session.commit()
            if (i // args.batch) % 10 == 0:
                print(f'  …processed {n_proc}/{len(rows)}  changed={n_changed}',
                      flush=True)

        if args.apply:
            db.session.commit()
        print('', flush=True)
        print(f'=== TOTALS ===', flush=True)
        print(f'  processed:     {n_proc}', flush=True)
        print(f'  deals changed: {n_changed}', flush=True)
        print(f'  values set:    {n_values_set}', flush=True)
        if not args.apply:
            print('', flush=True)
            print('DRY-RUN — ничего не записано. --apply для реального.',
                  flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
