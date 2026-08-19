"""
Нормализация имён категорий: приведение к единому виду
«Первая буква заглавная, остальное строчными», с сохранением аббревиатур
в оригинальном (обычно капсовом) написании — иначе `«POS-моноблоки»` после
Python-овского `.capitalize()` превратилось бы в `«Pos-моноблоки»`.

Список аббревиатур можно пополнять — это единственная точка правды.
Резолвер (`services/category_resolver.py`) и миграционный скрипт
(`scripts/normalize_categories.py`) должны использовать эту же функцию.
"""

import re

# Аббревиатуры, которые остаются в своём каноничном написании (регистр!).
# Ключ — lower-версия, значение — как выводить. Дополняй список по мере
# появления новых кейсов от поставщиков.
ABBR_MAP = {
    'pos':  'POS',
    'usb':  'USB',
    'hdd':  'HDD',
    'ssd':  'SSD',
    'led':  'LED',
    'oled': 'OLED',
    'qled': 'QLED',
    'lcd':  'LCD',
    'ips':  'IPS',
    'rfid': 'RFID',
    'nfc':  'NFC',
    'ble':  'BLE',
    'iot':  'IoT',
    'wifi': 'WiFi',
    'atm':  'ATM',
    'id':   'ID',
    'erp':  'ERP',
    'crm':  'CRM',
    'it':   'IT',
    '3d':   '3D',
    'hd':   'HD',
    '4k':   '4K',
    '8k':   '8K',
    'ai':   'AI',
    'ar':   'AR',
    'vr':   'VR',
    'gps':  'GPS',
    'gsm':  'GSM',
    'sim':  'SIM',
    'sd':   'SD',
    'ip':   'IP',
    'tv':   'TV',
    'dvd':  'DVD',
    'cd':   'CD',
    'vip':  'VIP',
    'pdf':  'PDF',
    'xml':  'XML',
    'json': 'JSON',
    'api':  'API',
    'sdk':  'SDK',
    'ui':   'UI',
    'ux':   'UX',
}

# Токенизатор: сохраняет разделители (пробел / дефис / слэш) — чтобы
# «POS-моноблоки» остались «POS-моноблоки», а не превратились в
# «Pos моноблоки». Слова и разделители чередуются в результате split.
_TOKEN_RE = re.compile(r'([^\s\-/]+|[\s\-/]+)')


def _is_separator(w: str) -> bool:
    return bool(w) and all(c in ' -/' for c in w)


def _norm_word(w: str, capitalize: bool) -> str:
    """
    Нормализует одно слово. capitalize=True — первая буква заглавная,
    остальные строчные (только для самого первого слова во всей строке).
    False — всё слово в lower. Аббревиатуры всегда идут через ABBR_MAP.
    """
    if not w:
        return w
    canonical = ABBR_MAP.get(w.lower())
    if canonical is not None:
        return canonical
    if capitalize:
        return w[0].upper() + w[1:].lower()
    return w.lower()


def normalize_name(raw: str) -> str:
    """
    Возвращает нормализованное имя категории:
      - .strip() по краям
      - первое буквенное слово: первая буква заглавная, остальные строчные
      - все последующие слова: полностью строчные
      - аббревиатуры (POS/USB/WiFi/…) сохраняют канонич. написание из ABBR_MAP
      - разделители (пробел, дефис, слэш) сохраняются как есть

    Примеры:
      «ХОЛОДИЛЬНОЕ ОБОРУДОВАНИЕ» → «Холодильное оборудование»
      «параконвектоматные аппараты» → «Параконвектоматные аппараты»
      «POS-моноблоки» → «POS-моноблоки»
      «wifi роутеры» → «WiFi роутеры»
      «оборудование для FAST FOOD» → «Оборудование для fast food»
        (FAST/FOOD не аббревиатуры из нашего списка — становятся lower)
    """
    if not raw:
        return ''
    stripped = raw.strip()
    if not stripped:
        return ''
    parts = _TOKEN_RE.findall(stripped)
    out = []
    first_word_seen = False
    for p in parts:
        if _is_separator(p):
            out.append(p)
            continue
        out.append(_norm_word(p, capitalize=not first_word_seen))
        first_word_seen = True
    return ''.join(out)
