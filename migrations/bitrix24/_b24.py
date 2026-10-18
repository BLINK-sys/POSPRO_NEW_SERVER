"""
Общий HTTP-клиент для Bitrix24 inbound webhook'а.

Webhook задан через env `B24_WEBHOOK` (вида
`https://pospro24.bitrix24.kz/rest/<user_id>/<token>` — БЕЗ слеша в конце).

Все методы Б24 постгарантированно idempotent на read: GET-запрос ничего
не меняет. Для write (crm.* add/update) этот модуль не используется —
миграция только читает Б24, записывает в наш PosPro.
"""

import os
import time
import urllib.parse
import urllib.request
import json


def _webhook_base() -> str:
    url = os.environ.get('B24_WEBHOOK', '').rstrip('/')
    if not url:
        raise RuntimeError(
            'B24_WEBHOOK env var is not set. '
            'Задайте его в Render → Environment перед запуском миграции.'
        )
    return url


def call(method: str, params: dict | None = None, *, timeout: int = 30) -> dict:
    """
    Вызывает метод Б24. Возвращает полный ответ (dict с ключами
    `result`, опц. `total`, `next`, `error_description`).

    Б24 стандартный rate-limit: 2 req/s на хук. Делаем мягкую паузу
    50мс между запросами, чтобы не словить 503.
    """
    url = f'{_webhook_base()}/{method}.json'
    data = urllib.parse.urlencode(params or {}, doseq=True).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(
            f'B24 {method} HTTP {e.code}: {body[:300]}'
        ) from e
    out = json.loads(body)
    if 'error' in out:
        raise RuntimeError(
            f'B24 {method}: {out.get("error_description") or out.get("error")}'
        )
    time.sleep(0.05)
    return out


def iter_list(method: str, params: dict | None = None):
    """
    Итерируется по пагинированному методу Б24 (использует `start` cursor
    и поле `next` в ответе). yield-ит сущности по одной.
    """
    p = dict(params or {})
    start = 0
    while True:
        p['start'] = start
        out = call(method, p)
        items = out.get('result') or []
        if isinstance(items, dict):
            # Некоторые методы возвращают result как dict с массивом внутри.
            items = (items.get('items')
                     or items.get('contacts')
                     or items.get('companies')
                     or items.get('deals')
                     or items.get('tasks')
                     or [])
        for it in items:
            yield it
        nxt = out.get('next')
        if nxt is None:
            return
        start = int(nxt)
