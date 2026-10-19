"""
Диагностика «обязательных полей на стадии» для воронок B24.

В B24 есть встроенный механизм: для каждой стадии (DEAL_STAGE) можно
отметить какие поля обязательны к заполнению. Хранится это разными
путями — тут мы прощупываем все известные:

  1. crm.dealcategory.list                       — список воронок
  2. crm.dealcategory.stage.list(id=…)           — стадии воронки
  3. crm.dealcategory.default.get                — дефолтная воронка
  4. crm.dealcategory.get(id=…)                  — поля воронки
  5. crm.deal.userfield.list                     — у каждого UF есть
     MANDATORY: Y/N — это ГЛОБАЛЬНЫЙ флажок, не per-stage
  6. userfieldconfig.list / userfieldconfig.get  — конфиг обязательности
     per-category/per-stage (если доступно на портале)
  7. crm.automation.trigger.list / robot.list    — автоматизация на стадии,
     иногда там же сидят проверки

Запуск:
    python -u -m migrations.b24_required_fields_diag
    python -u -m migrations.b24_required_fields_diag --category-id 2
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from migrations.bitrix24._b24 import call


def _dump(label: str, obj, limit: int | None = None) -> None:
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if limit and len(s) > limit:
        s = s[:limit] + f'\n…[обрезано, {len(s)} байт]'
    print(f'--- {label} ---', flush=True)
    print(s, flush=True)
    print('', flush=True)


def _safe_call(method: str, params: dict | None = None):
    try:
        r = call(method, params or {})
        return r
    except Exception as e:
        return {'__error__': str(e)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--category-id', type=int, default=None,
                   help='Если задан — углублённый diag по конкретной воронке')
    args = p.parse_args()

    with app.app_context():
        print('=== 1. crm.dealcategory.list — воронки ===', flush=True)
        r = _safe_call('crm.dealcategory.list', {'order[SORT]': 'ASC'})
        _dump('result', r.get('result') if isinstance(r, dict) else r, 4000)

        # Также дефолтная "воронка 0" — у неё отдельный id-механизм.
        print('=== 2. crm.dealcategory.default.get ===', flush=True)
        r = _safe_call('crm.dealcategory.default.get')
        _dump('result', r.get('result') if isinstance(r, dict) else r, 2000)

        # Поля сделки — у каждого MANDATORY: Y/N это глобально.
        print('=== 3. crm.deal.fields — встроенные поля (ищем MANDATORY) ===',
              flush=True)
        r = _safe_call('crm.deal.fields')
        fields = r.get('result') if isinstance(r, dict) else {}
        if isinstance(fields, dict):
            mandatory = {
                k: {kk: v[kk] for kk in ('title', 'type', 'isRequired', 'isReadOnly')
                    if kk in v}
                for k, v in fields.items()
                if isinstance(v, dict) and v.get('isRequired')
            }
            _dump('MANDATORY встроенные поля', mandatory, 3000)

        # UF-поля — у них MANDATORY: Y/N это настройка на уровне поля.
        print('=== 4. crm.deal.userfield.list — UF с MANDATORY=Y ===',
              flush=True)
        r = _safe_call('crm.deal.userfield.list', {
            'order': {'SORT': 'ASC'},
            'filter': {},
        })
        ufs = r.get('result') if isinstance(r, dict) else []
        mandatory_ufs = []
        for u in (ufs or []):
            if u.get('MANDATORY') == 'Y':
                mandatory_ufs.append({
                    'FIELD_NAME': u.get('FIELD_NAME'),
                    'LABEL': (u.get('EDIT_FORM_LABEL') or {}).get('ru')
                             or (u.get('LIST_COLUMN_LABEL') or {}).get('ru')
                             or u.get('FIELD_NAME'),
                    'USER_TYPE_ID': u.get('USER_TYPE_ID'),
                })
        _dump(f'MANDATORY UF ({len(mandatory_ufs)}/{len(ufs or [])})',
              mandatory_ufs, 4000)

        # Углублённый diag — для конкретной воронки.
        cat_id = args.category_id
        if cat_id is None:
            # Берём первую не-дефолтную.
            lst = _safe_call('crm.dealcategory.list', {}).get('result') or []
            if lst:
                cat_id = int(lst[0].get('ID'))
        if cat_id is not None:
            print(f'=== 5. crm.dealcategory.stage.list(id={cat_id}) — '
                  f'стадии воронки {cat_id} ===', flush=True)
            r = _safe_call('crm.dealcategory.stage.list', {'id': cat_id})
            _dump('stages', r.get('result') if isinstance(r, dict) else r, 4000)

            print(f'=== 6. crm.dealcategory.get(id={cat_id}) ===', flush=True)
            r = _safe_call('crm.dealcategory.get', {'id': cat_id})
            _dump('dealcategory', r.get('result') if isinstance(r, dict) else r,
                  3000)

        # Попробуем недокументированный, но распространённый метод
        # userfieldconfig — вдруг он есть у этого портала.
        print('=== 7. userfieldconfig.list (может не быть) ===', flush=True)
        r = _safe_call('userfieldconfig.list', {
            'moduleId': 'crm',
            'entityId': 'CRM_DEAL',
        })
        _dump('result', r, 2000)

        # Автоматизация на стадиях — там иногда «валидатор поля».
        print('=== 8. crm.automation.trigger.list (для DEAL + category) ===',
              flush=True)
        r = _safe_call('crm.automation.trigger.list', {
            'DOCUMENT_TYPE': ['crm', 'CCrmDocumentDeal', 'DEAL'],
        })
        _dump('result', r, 2000)

        print('=== 9. crm.automation.robot.list ===', flush=True)
        r = _safe_call('crm.automation.robot.list', {
            'DOCUMENT_TYPE': ['crm', 'CCrmDocumentDeal', 'DEAL'],
        })
        _dump('result', r, 2000)

        print('--- END OF DIAG ---', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
