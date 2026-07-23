"""
Пресеты формул ценообразования по типам складов.

Тип склада определяется парой (валюта, vat_enabled):
- Валюта != KZT           → РФ-подобный (импорт): НДС начисляется поверх
                            конвертированной себестоимости, доставка добавляется
                            к себестоимости, потом торговая наценка.
- KZT, vat_enabled=True   → КЗ с НДС: закуп уже с НДС, доставка добавляется,
                            торговая наценка сверху.
- KZT, vat_enabled=False  → КЗ без НДС (без документов / упрощёнка):
                            закуп чистый, доставка добавляется, торговая
                            наценка сверху.

Розничная цена везде включает 16% НДС на выходе.

Переменные, доступные внутри формул:
- себестоимость       — cost_price из ProductWarehouseCost (в валюте склада)
- курс_валюты         — Currency.rate_to_tenge
- НДС                 — встроенная константа 1.16 (см. formula_engine.VAT_MUL)
- Доставка            — результат delivery_formula (0 если не задана)
- коэф_наценки        — переменная склада (по умолчанию 1.16)

delivery_formula и cost_formula не трогаем — они настраиваются оператором отдельно.
"""

MARGIN_VAR_NAME = 'коэф_наценки'
MARGIN_VAR_DEFAULT = '1.16'
MARGIN_VAR_LABEL = 'Торговая наценка (множитель, 1.16 = +16%)'

PRESET_RF = 'ceil((себестоимость * курс_валюты * НДС + Доставка) * коэф_наценки / 100) * 100'
PRESET_KZ_VAT = 'ceil((себестоимость + Доставка) * коэф_наценки / 100) * 100'
PRESET_KZ_NOVAT = 'ceil((себестоимость + Доставка) * коэф_наценки / 100) * 100'


def select_price_formula(currency_code: str, vat_enabled: bool) -> str:
    """Вернуть строку розничной формулы для указанного типа склада."""
    code = (currency_code or '').upper().strip()
    if code != 'KZT':
        return PRESET_RF
    if vat_enabled:
        return PRESET_KZ_VAT
    return PRESET_KZ_NOVAT


def warehouse_type_label(currency_code: str, vat_enabled: bool) -> str:
    """Человеческое имя типа склада — для логов/UI."""
    code = (currency_code or '').upper().strip()
    if code != 'KZT':
        return 'РФ / импорт'
    return 'КЗ с НДС' if vat_enabled else 'КЗ без НДС'
