"""
Core-логика автосоздания сделок из ingest-источников.

Используется двумя точками входа:
1. Внутренние вызовы из бэка (обработчики заказов, уточнений цены).
   Вызывается напрямую как `ingest(source_key=..., payload=...)`.
2. Внешний webhook (`POST /api/webhooks/crm/ingest/<token>`). Роут
   находит `crm_ingest_source` по токену и вызывает `_apply(rule, payload)`.

Payload — свободный JSON. Все поля опциональные, кроме `source_ref_id`
(нужен для дедупликации). Формат см. в 31 CRM (Обсидиан).

Flow (`_apply`):
1. Дедупликация: если `dedupe_by_ref=true` и уже есть сделка с
   (source_ref_type, source_ref_id) — возвращаем существующий id,
   новую не создаём.
2. Резолвим клиента по `client_resolution` — kp_client id или None.
3. Выбираем ответственного через `_pick_responsible` — по стратегии
   round_robin / least_busy / fixed / unassigned.
4. Рендерим title/notes-шаблоны с плейсхолдерами.
5. Создаём Deal.
6. Пишем `deal_activity` kind='created_from_source' с полным payload.
7. Обновляем статистику rule (last_used_at, request_count, для
   round_robin — assignment_index).

Возвращает `IngestResult` (dataclass) с deal_id, responsible_id и флагом
`dedupe` (True если сделка уже была).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func

from extensions import db
from models.crm_ingest_source import CrmIngestSource
from models.deal import Deal, DealActivity
from models.kp_client import KpClient


@dataclass
class IngestResult:
    ok: bool
    deal_id: int | None = None
    responsible_id: int | None = None
    dedupe: bool = False
    error: str | None = None


# ============================================================================
# Public API
# ============================================================================

def ingest(source_key: str, payload: dict) -> IngestResult:
    """
    Точка входа для внутренних вызовов (обработчики orders / price_requests).
    Ищет активное правило по (kind='internal', source_key=source_key).
    Если правило не настроено или неактивно — тихий no-op (не ошибка).
    """
    rule = CrmIngestSource.query.filter_by(
        kind='internal', source_key=source_key, active=True,
    ).one_or_none()
    if not rule:
        # Нет правила — тихо игнорируем. Это НЕ ошибка: админ мог
        # осознанно выключить конкретный источник.
        return IngestResult(ok=True)
    return _apply(rule, payload)


def apply_webhook(token: str, payload: dict) -> IngestResult:
    """
    Точка входа для `/api/webhooks/crm/ingest/<token>`. Роут отдаёт
    результат клиенту — если правило не найдено или выключено, тут
    ошибка (в отличие от internal-варианта).
    """
    if not token or not isinstance(token, str):
        return IngestResult(ok=False, error='Токен не указан')

    rule = CrmIngestSource.query.filter_by(
        kind='webhook', token=token, active=True,
    ).one_or_none()
    if not rule:
        return IngestResult(ok=False, error='Webhook не найден или выключен')
    return _apply(rule, payload)


# ============================================================================
# Core apply
# ============================================================================

def _apply(rule: CrmIngestSource, payload: dict) -> IngestResult:
    payload = payload or {}
    source_ref_id = _get_str(payload, 'source_ref_id')
    source_ref_type = rule.source_key if rule.kind == 'internal' else f'webhook:{rule.token[:8]}'

    # 1) Дедупликация — сделка с тем же source_ref_id уже есть.
    if rule.dedupe_by_ref and source_ref_id:
        existing = Deal.query.filter_by(
            source_ref_type=source_ref_type, source_ref_id=source_ref_id,
        ).first()
        if existing:
            _touch_stats(rule)
            db.session.commit()
            return IngestResult(
                ok=True, deal_id=existing.id,
                responsible_id=existing.responsible_user_id,
                dedupe=True,
            )

    # 2) Клиент.
    client_id = _resolve_client(rule, payload)

    # 3) Ответственный.
    responsible_id = _pick_responsible(rule)

    # 4) Шаблоны.
    title = _render_template(rule.title_template or 'Сделка', payload) or 'Сделка'
    notes = _render_template(rule.notes_template, payload) if rule.notes_template else None

    # 5) Deal.
    deal = Deal(
        name=title[:255],
        client_id=client_id,
        responsible_user_id=responsible_id,
        pipeline_id=rule.pipeline_id,
        stage_id=rule.stage_id,
        amount=_get_decimal(payload, 'amount'),
        currency=_get_str(payload, 'currency') or 'KZT',
        priority=_get_str(payload, 'priority') or rule.priority,
        source='ingest',
        status='open',
        tags=[],
        notes=notes,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
    )
    db.session.add(deal)
    db.session.flush()  # получаем deal.id

    # 6) Activity.
    db.session.add(DealActivity(
        deal_id=deal.id, user_id=None, kind='created_from_source',
        payload={
            'source_kind': rule.kind,
            'source_name': rule.name,
            'source_key': rule.source_key,
            'token_prefix': (rule.token or '')[:8] if rule.token else None,
            'responsible_id': responsible_id,
            'client_id': client_id,
            'raw_payload': _redact_for_activity(payload),
        },
    ))

    # 7) Статистика rule.
    _touch_stats(rule)

    db.session.commit()

    # 7.5) Автосоздание чата для ingested-сделки. Ответственный (если
    # есть) сразу становится участником — creator тут system, не
    # добавляем. best-effort: сбой не валит основной путь, чат позже
    # создастся ленивой инициализацией в GET /deals/<id>/chat-room.
    try:
        from models.chat import ChatRoom, ChatMember
        chat_room = ChatRoom(kind='deal', related_deal_id=deal.id)
        db.session.add(chat_room)
        db.session.flush()
        if responsible_id:
            db.session.add(ChatMember(room_id=chat_room.id, user_id=responsible_id))
        db.session.commit()
    except Exception as e:
        print(f'⚠️ ingest chat auto-create failed for deal {deal.id}: {e}', flush=True)

    # 8) Уведомление ответственному если назначен. best-effort — при
    # сбое ingest в целом всё равно успешен.
    if responsible_id:
        try:
            from services.notifications import notify
            notify(
                user_id=responsible_id, kind='deal_ingest_arrived',
                section='deals', entity_type='deal', entity_id=deal.id,
                payload={
                    'deal_name': deal.name,
                    'source_kind': rule.kind,
                    'source_name': rule.name,
                },
                push_title='Новая сделка из источника',
                push_body=f'{rule.name}: {deal.name}',
                push_url=f'/admin/deals/{deal.id}',
            )
            db.session.commit()
        except Exception as e:
            print(f'⚠️ notify (ingest) failed: {e}', flush=True)

    return IngestResult(
        ok=True, deal_id=deal.id,
        responsible_id=responsible_id, dedupe=False,
    )


# ============================================================================
# Client resolution
# ============================================================================

def _resolve_client(rule: CrmIngestSource, payload: dict) -> int | None:
    """
    По `rule.client_resolution` — либо не трогаем клиента (None), либо
    ищем/создаём в `kp_client`. Возвращает kp_client.id или None.
    """
    mode = rule.client_resolution or 'none'
    if mode == 'none':
        return None

    client_data = payload.get('client') or {}
    if not isinstance(client_data, dict):
        client_data = {}
    name = _get_str(client_data, 'name') or _get_str(payload, 'client_name')
    email = _get_str(client_data, 'email') or _get_str(payload, 'client_email')
    phone = _get_str(client_data, 'phone') or _get_str(payload, 'client_phone')

    if mode == 'always_create':
        if not (name or phone or email):
            return None
        return _create_client(name, email, phone, client_data)

    if mode == 'find_by_email':
        if email:
            existing = _find_client_by_contact(email=email)
            if existing:
                return existing.id
        if name or phone or email:
            return _create_client(name, email, phone, client_data)
        return None

    if mode == 'find_by_phone':
        if phone:
            existing = _find_client_by_contact(phone=phone)
            if existing:
                return existing.id
        if name or phone or email:
            return _create_client(name, email, phone, client_data)
        return None

    return None


def _find_client_by_contact(*, email: str | None = None, phone: str | None = None) -> KpClient | None:
    """
    Ищем клиента по contacts jsonb — там элементы {phone, note}. Email в
    contacts не хранится, но менеджеры часто пишут «email: xxx» в note,
    поэтому подстрочный поиск по note тоже допустим (best-effort).
    """
    if email:
        # По name/object ищем клиента у которого email в contacts.note или в object.
        like = f'%{email.lower()}%'
        c = KpClient.query.filter(
            db.func.lower(db.func.coalesce(KpClient.object, '')).like(like)
        ).first()
        if c:
            return c
        # JSONB fallback — pg_json path через text() не поддерживает LOWER,
        # так что ILIKE по всему contacts как строке.
        c = KpClient.query.filter(
            db.func.cast(KpClient.contacts, db.String).ilike(like)
        ).first()
        return c
    if phone:
        normalized = _normalize_phone(phone)
        # Тот же ILIKE-подход по JSONB — pg_trgm не нужен, объёмы малые.
        like = f'%{normalized}%'
        c = KpClient.query.filter(
            db.func.cast(KpClient.contacts, db.String).ilike(like)
        ).first()
        return c
    return None


def _create_client(name: str | None, email: str | None, phone: str | None, extra: dict) -> int | None:
    contacts = []
    if phone:
        note_parts = []
        if email:
            note_parts.append(f'email: {email}')
        company = _get_str(extra, 'company')
        if company:
            note_parts.append(company)
        contacts.append({
            'phone': phone,
            'note': ', '.join(note_parts) if note_parts else '',
        })

    company = _get_str(extra, 'company')
    obj_parts = []
    if company:
        obj_parts.append(company)
    if email and not phone:  # если телефона нет, email кладём в object
        obj_parts.append(f'email: {email}')
    client = KpClient(
        full_name=name or '(без имени)',
        object=', '.join(obj_parts) or None,
        contacts=contacts,
        created_by=None,
    )
    db.session.add(client)
    db.session.flush()
    return client.id


def _normalize_phone(raw: str) -> str:
    """Только цифры — для поиска-подстрокой в JSONB, без разделителей."""
    return re.sub(r'\D', '', raw or '')


# ============================================================================
# Responsible picking
# ============================================================================

def _pick_responsible(rule: CrmIngestSource) -> int | None:
    strategy = rule.assignment_strategy
    pool: list[int] = rule.pool_user_ids or []

    if strategy == 'fixed':
        return rule.fixed_user_id

    if strategy == 'round_robin':
        if not pool:
            return None
        idx = int(rule.assignment_index or 0) % len(pool)
        rule.assignment_index = (idx + 1) % max(len(pool), 1)
        return pool[idx]

    if strategy == 'least_busy':
        if not pool:
            return None
        counts = dict(
            db.session.query(
                Deal.responsible_user_id, func.count(Deal.id)
            )
            .filter(
                Deal.responsible_user_id.in_(pool),
                Deal.pipeline_id == rule.pipeline_id,
                Deal.status == 'open',
            )
            .group_by(Deal.responsible_user_id)
            .all()
        )
        # Tie-break — round-robin через assignment_index. Сортируем по
        # (count, position_in_pool) чтобы при равных счётчиках юзеры
        # выбирались по порядку в пуле.
        sorted_pool = sorted(pool, key=lambda uid: (counts.get(uid, 0), pool.index(uid)))
        pick = sorted_pool[0]
        # Прокручиваем assignment_index для tie-break стабильности.
        rule.assignment_index = (int(rule.assignment_index or 0) + 1) % max(len(pool), 1)
        return pick

    # strategy == 'unassigned' или невалидная — не назначаем.
    return None


# ============================================================================
# Template rendering
# ============================================================================

# Простой рендерер вида {a.b} — поддерживает вложенность на 1 уровень
# ({client.name}). Ничего сложного не нужно — плейсхолдеры пишет админ.
_PLACEHOLDER = re.compile(r'\{([a-zA-Z_][a-zA-Z0-9_.]*)\}')


def _render_template(template: str | None, payload: dict) -> str | None:
    if not template:
        return None

    def replace(match: re.Match) -> str:
        path = match.group(1)
        val = _get_by_path(payload, path)
        if val is None:
            return ''
        return str(val)

    return _PLACEHOLDER.sub(replace, template).strip()


def _get_by_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split('.'):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


# ============================================================================
# Helpers
# ============================================================================

def _get_str(data: dict, key: str) -> str | None:
    v = data.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _get_decimal(data: dict, key: str) -> float | None:
    v = data.get(key)
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _touch_stats(rule: CrmIngestSource) -> None:
    """Обновляем статистику rule. commit — снаружи."""
    rule.last_used_at = datetime.utcnow()
    rule.request_count = (rule.request_count or 0) + 1


def _redact_for_activity(payload: dict, max_keys: int = 20) -> dict:
    """
    Ужимаем raw-payload для записи в activity: пропускаем очень длинные
    строки и обрезаем размер, чтобы не раздувать deal_activity.payload.
    """
    if not isinstance(payload, dict):
        return {'_raw': str(payload)[:500]}
    out = {}
    for i, (k, v) in enumerate(payload.items()):
        if i >= max_keys:
            out['_truncated'] = True
            break
        if isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + '…'
        else:
            out[k] = v
    return out
