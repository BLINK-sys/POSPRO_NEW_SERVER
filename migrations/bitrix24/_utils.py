"""
Утилиты для миграции из Б24.

- user_pospro_id(mapping, b24_id, owner_fallback) — находит id нашего
  system_users по b24_id через b24_meta.mapping.users.
- normalize_phone(raw) — приводит номер к KZ-формату +7 (XXX) XXX-XX-XX
  как делает фронт в lib/utils.ts.
- mirror_get/mirror_set — чтение/запись b24_mirror для идемпотентности.
"""

import re
from extensions import db
from sqlalchemy import text as sql_text


def load_mapping() -> dict:
    row = db.session.execute(
        sql_text("SELECT value FROM b24_meta WHERE key='mapping'")
    ).fetchone()
    if not row:
        raise RuntimeError('b24_meta.mapping is empty — run fix_mapping first')
    import json
    v = row[0]
    if isinstance(v, str):
        v = json.loads(v)
    return v


def user_pospro_id(mapping: dict, b24_id, owner_fallback: int) -> int:
    """
    Находит pospro_id нашего system_users по b24-user-id. Если не нашли
    (например assigned_by новый юзер) — возвращает owner_fallback (owner
    пропустить сделку нельзя — она сломает FK).
    """
    if b24_id in (None, '', 0, '0'):
        return owner_fallback
    key = str(b24_id)
    v = mapping.get('users', {}).get('map', {}).get(key)
    if v and v.get('pospro_id'):
        return int(v['pospro_id'])
    return owner_fallback


def stage_ids_for_b24(mapping: dict, b24_stage_id: str) -> tuple[int, int] | None:
    """
    Возвращает (pospro_pipeline_id, pospro_stage_id) для Б24-стадии.
    Если stage не замаплен — None.
    """
    v = mapping.get('stages', {}).get(b24_stage_id)
    if not v:
        return None
    pid = v.get('pospro_pipeline_id')
    sid = v.get('pospro_stage_id')
    if not pid or not sid:
        return None
    return int(pid), int(sid)


# ---------------------------------------------------------------------------
# Phone normalization — повторяет formatPhone из pospro_new_ui/lib/utils.ts.
# Для KZ-номеров: 10 цифр после 7 → "+7 (XXX) XXX-XX-XX".
# ---------------------------------------------------------------------------

def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None
    # Нормализуем ведущую цифру: 8 → 7, если 10 цифр без кода страны — 7+.
    if len(digits) == 11 and digits[0] in ('8', '7'):
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits
    if len(digits) != 11 or digits[0] != '7':
        # Нешаблонный номер — вернём как ввели (минус пробелы).
        return re.sub(r'\s+', ' ', raw.strip())
    return f'+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}'


def phone_digits(raw: str | None) -> str:
    """Только цифры для сравнения на дедуп."""
    return re.sub(r'\D', '', raw or '')


# ---------------------------------------------------------------------------
# b24_mirror — трекинг (entity_type, b24_id) → pospro_id
# ---------------------------------------------------------------------------

def mirror_get(entity_type: str, b24_id) -> int | None:
    from models.b24_mirror import B24Mirror
    row = B24Mirror.query.filter_by(
        entity_type=entity_type, b24_id=str(b24_id),
    ).first()
    return row.pospro_id if row else None


def mirror_set(entity_type: str, b24_id, pospro_id: int,
               tag: str = 'initial') -> None:
    """UPSERT в b24_mirror. Если уже есть — обновим pospro_id."""
    from models.b24_mirror import B24Mirror
    existing = B24Mirror.query.filter_by(
        entity_type=entity_type, b24_id=str(b24_id),
    ).first()
    if existing:
        if existing.pospro_id != pospro_id:
            existing.pospro_id = pospro_id
        return
    db.session.add(B24Mirror(
        entity_type=entity_type,
        b24_id=str(b24_id),
        pospro_id=pospro_id,
        migration_tag=tag,
    ))
