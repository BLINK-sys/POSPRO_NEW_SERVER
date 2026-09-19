"""
Сервис уведомлений: создание записей в `notification` + отправка Web Push.

Публичный API:
- notify(user_id, kind, section, entity_type=None, entity_id=None,
         payload=None, push_title=None, push_body=None, push_url=None)
  Создаёт Notification и (если задан push_title/body и есть VAPID-ключи)
  шлёт Web Push во все подписки юзера.

- notify_many(user_ids, **kwargs) — то же для списка юзеров.

- send_web_push(subscription, title, body, url=None, ttl=60)
  Низкоуровневый send. Возвращает True если успешно, False + печатает
  причину если нет.

VAPID-ключи из env:
- VAPID_PUBLIC_KEY   (base64url, для клиента через /vapid-public endpoint)
- VAPID_PRIVATE_KEY  (base64url, только на бэке)
- VAPID_SUBJECT      (mailto:… — обязательно для Web Push протокола)

Генерация ключей (разово, локально):
    from pywebpush import Vapid
    v = Vapid()
    v.generate_keys()
    print('public:', v.public_key.public_bytes(...))
    print('private:', v.private_key.private_bytes(...))

Если ключей нет — `notify()` создаёт Notification, но push-часть тихо
пропускается (в консоль печатается warning). Так фича «постепенно
включается»: сначала bell-иконка, потом push после добавления env.
"""

from __future__ import annotations

import os
from datetime import datetime

from extensions import db
from models.notification import Notification, WebPushSubscription


# ============================================================================
# VAPID config
# ============================================================================

VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '').strip()
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '').strip()
VAPID_SUBJECT = os.getenv('VAPID_SUBJECT', 'mailto:admin@pospro.kz').strip()


def is_web_push_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


# ============================================================================
# Public API
# ============================================================================

def notify(
    user_id: int,
    *,
    kind: str,
    section: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    payload: dict | None = None,
    push_title: str | None = None,
    push_body: str | None = None,
    push_url: str | None = None,
) -> Notification:
    """
    Создаёт запись Notification для юзера. Если задан push_title/body —
    также шлёт Web Push во все подписки юзера (best-effort).

    commit — снаружи. Мы не коммитим, потому что вызов может быть в
    середине другой транзакции (например при stage_changed сделки).
    """
    n = Notification(
        user_id=user_id,
        kind=kind,
        section=section,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
    )
    db.session.add(n)
    db.session.flush()

    if push_title and push_body and is_web_push_configured():
        subs = WebPushSubscription.query.filter_by(user_id=user_id).all()
        for sub in subs:
            ok = send_web_push(sub, push_title, push_body, url=push_url)
            if ok:
                sub.last_used_at = datetime.utcnow()

    return n


def notify_many(user_ids: list[int], **kwargs) -> list[Notification]:
    """Batch-удобство. Ничего не оптимизирует — просто цикл."""
    out = []
    for uid in user_ids:
        out.append(notify(uid, **kwargs))
    return out


# ============================================================================
# Web Push send
# ============================================================================

def send_web_push(
    sub: WebPushSubscription,
    title: str,
    body: str,
    *,
    url: str | None = None,
    ttl: int = 60,
) -> bool:
    """
    Шлёт push через pywebpush. Возвращает True если ушло, False + печатает
    причину если нет.

    Если endpoint протух (410 Gone) — удаляем подписку из БД, чтобы не
    засорять.
    """
    if not is_web_push_configured():
        return False

    try:
        from pywebpush import webpush, WebPushException  # ленивая загрузка
    except ImportError:
        print('⚠️ pywebpush не установлен — push пропущен', flush=True)
        return False

    import json
    payload_json = json.dumps({
        'title': title,
        'body': body,
        'url': url or '/admin',
    }, ensure_ascii=False)

    try:
        webpush(
            subscription_info=sub.to_web_push_info(),
            data=payload_json,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={'sub': VAPID_SUBJECT},
            ttl=ttl,
        )
        return True
    except Exception as e:
        # pywebpush.WebPushException и всё что вылетит — обрабатываем
        # одинаково: печатаем, если 404/410 — удаляем.
        message = str(e)
        status = None
        try:
            from pywebpush import WebPushException as _WPE
            if isinstance(e, _WPE) and hasattr(e, 'response') and e.response is not None:
                status = e.response.status_code
        except Exception:
            pass

        print(f'⚠️ Web Push failed for sub={sub.id} user={sub.user_id}: {message}', flush=True)

        if status in (404, 410):
            # Подписка мертва — чистим.
            print(f'   → удаляем подписку sub={sub.id}', flush=True)
            db.session.delete(sub)
        return False
