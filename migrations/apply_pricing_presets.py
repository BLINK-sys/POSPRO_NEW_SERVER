"""
Разовая миграция: применить стандартные пресеты розничной формулы
и переменную `коэф_наценки` ко ВСЕМ существующим складам.

Что делает:
1. Обходит все Warehouse
2. По (currency.code, vat_enabled) определяет тип склада
3. Устанавливает WarehouseFormula.formula = соответствующий пресет
4. Если переменной `коэф_наценки` на складе нет — создаёт со значением 1.16
5. delivery_formula, cost_formula и прочие переменные НЕ ТРОГАЕТ

Что НЕ делает:
- Не запускает пересчёт цен товаров — это ручной шаг оператора
  (в UI склада есть кнопка «Пересчитать склад»).

Запуск (в Render Shell или локально с настроенным DATABASE_URL):
    cd pospro_new_server
    python -m migrations.apply_pricing_presets

Идемпотентна: повторный запуск не создаёт дубли и переустанавливает
formula в тот же пресет.
"""

import sys
import os

# Гарантируем что импорты приложения найдутся когда скрипт запускается
# как `python -m migrations.apply_pricing_presets` из pospro_new_server/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from models.warehouse import Warehouse, WarehouseVariable, WarehouseFormula
from utils.pricing_presets import (
    MARGIN_VAR_NAME, MARGIN_VAR_DEFAULT, MARGIN_VAR_LABEL,
    select_price_formula, warehouse_type_label,
)


def apply_presets():
    warehouses = Warehouse.query.order_by(Warehouse.id).all()

    stats = {
        'total': len(warehouses),
        'formula_set': 0,
        'formula_created': 0,
        'margin_var_created': 0,
        'margin_var_kept': 0,
        'errors': [],
    }

    for wh in warehouses:
        currency_code = wh.currency.code if wh.currency else ''
        preset = select_price_formula(currency_code, bool(wh.vat_enabled))
        type_label = warehouse_type_label(currency_code, bool(wh.vat_enabled))

        try:
            # 1. Установить formula
            if wh.formula:
                wh.formula.formula = preset
                stats['formula_set'] += 1
            else:
                wh.formula = WarehouseFormula(
                    warehouse_id=wh.id,
                    formula=preset,
                    delivery_formula=None,
                    cost_formula=None,
                )
                db.session.add(wh.formula)
                stats['formula_created'] += 1

            # 2. Обеспечить переменную коэф_наценки
            existing = next(
                (v for v in wh.variables if v.name == MARGIN_VAR_NAME),
                None,
            )
            if existing is None:
                max_sort = max((v.sort_order or 0 for v in wh.variables), default=0)
                new_var = WarehouseVariable(
                    warehouse_id=wh.id,
                    name=MARGIN_VAR_NAME,
                    label=MARGIN_VAR_LABEL,
                    formula=MARGIN_VAR_DEFAULT,
                    sort_order=max_sort + 1,
                )
                db.session.add(new_var)
                stats['margin_var_created'] += 1
            else:
                stats['margin_var_kept'] += 1

            print(f'  [{wh.id:>4}] {wh.name!r:<40} {type_label:<15} → OK')

        except Exception as exc:
            stats['errors'].append((wh.id, wh.name, str(exc)))
            print(f'  [{wh.id:>4}] {wh.name!r:<40} → ERROR: {exc}')

    if stats['errors']:
        print('\nЕсть ОШИБКИ — откатываю транзакцию')
        db.session.rollback()
    else:
        db.session.commit()
        print('\nCommit OK')

    print('\n=== ИТОГИ ===')
    print(f'  Всего складов:            {stats["total"]}')
    print(f'  formula обновлена:        {stats["formula_set"]}')
    print(f'  formula создана с нуля:   {stats["formula_created"]}')
    print(f'  коэф_наценки создана:     {stats["margin_var_created"]}')
    print(f'  коэф_наценки оставлена:   {stats["margin_var_kept"]}')
    print(f'  Ошибок:                   {len(stats["errors"])}')

    return len(stats['errors']) == 0


if __name__ == '__main__':
    with app.app_context():
        ok = apply_presets()
        sys.exit(0 if ok else 1)
