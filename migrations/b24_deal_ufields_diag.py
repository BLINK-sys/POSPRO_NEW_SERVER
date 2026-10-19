"""
Диагностика кастомных UF-полей сделок B24. Нужна чтобы понять откуда
реально брать «Источник» (сейчас импорт тащит SOURCE_ID, но пользователь
говорит что реальный источник — в каком-то UF_CRM_* поле).

Печатает:
  - весь список UF с FIELD_NAME, LABEL, TYPE, LIST (если enum с
    фиксированными значениями)
  - 15 самых свежих сделок: ID, TITLE, SOURCE_ID, и все UF-поля с
    непустыми значениями — чтобы сопоставить «что видно у Антона в UI»
    с реальным именем поля в API

Запуск:
    python -u -m migrations.b24_deal_ufields_diag
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from migrations.bitrix24._b24 import call


def main() -> int:
    with app.app_context():
        print('=== UF-поля сделок (crm.deal.userfield.list) ===', flush=True)
        try:
            r = call('crm.deal.userfield.list', {
                'order[SORT]': 'ASC',
            })
        except Exception as e:
            print(f'ERROR: {e}', flush=True)
            return 1
        fields = r.get('result') or []
        for f in fields:
            label = (f.get('LIST_COLUMN_LABEL') or {}).get('ru') \
                or (f.get('EDIT_FORM_LABEL') or {}).get('ru') \
                or f.get('FIELD_NAME')
            print(f'  {f.get("FIELD_NAME"):40s}  type={f.get("USER_TYPE_ID"):12s}  label={label!r}',
                  flush=True)
            # Для enum — выводим список значений
            if f.get('USER_TYPE_ID') == 'enumeration':
                items = f.get('LIST') or []
                for it in items[:30]:
                    print(f'       → id={it.get("ID"):>6}  value={it.get("VALUE")!r}',
                          flush=True)
                if len(items) > 30:
                    print(f'       … ещё {len(items) - 30}', flush=True)

        print('', flush=True)
        print('=== Примеры 15 свежих сделок (все UF-поля непустые + SOURCE_ID) ===',
              flush=True)
        try:
            r = call('crm.deal.list', {
                'order[DATE_CREATE]': 'DESC',
                'select[]': ['*', 'UF_*'],
                'start': 0,
            })
        except Exception as e:
            print(f'ERROR: {e}', flush=True)
            return 1
        deals = r.get('result') or []
        for d in deals[:15]:
            print('', flush=True)
            print(f'  deal #{d.get("ID")}  TITLE={d.get("TITLE")!r}', flush=True)
            print(f'    SOURCE_ID={d.get("SOURCE_ID")!r}  '
                  f'SOURCE_DESCRIPTION={(d.get("SOURCE_DESCRIPTION") or "")[:80]!r}',
                  flush=True)
            # Печатаем все UF с непустыми значениями
            for k, v in d.items():
                if not k.startswith('UF_'):
                    continue
                if v in (None, '', [], {}, '0', 0):
                    continue
                vshow = str(v)
                if len(vshow) > 120:
                    vshow = vshow[:120] + '…'
                print(f'    {k} = {vshow}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
