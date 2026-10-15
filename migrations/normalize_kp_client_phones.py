"""
Одноразовая нормализация телефонов в kp_client.contacts под единый
формат `+7 (XXX) XXX-XX-XX`.

Логика повторяет формул фронта (`lib/utils.formatPhone`):
    1) Удаляем всё, кроме цифр.
    2) Если начинается с 7 или 8 — отрезаем первый символ (нормализация
       международного кода к КЗ/РФ формату без начальной 7/8).
    3) Берём максимум 10 цифр.
    4) Форматируем в `+7 (DDD) DDD-DD-DD` (на сколько хватило цифр).

Безопасно: обрабатывает только поле `phone` каждого объекта в
`contacts` JSONB. `note` и всё остальное — не трогает. Если phone пустой
или оканчивается уже в целевом формате — остаётся как есть.

Запуск через Render Job:
    python -u -m migrations.normalize_kp_client_phones
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from models.kp_client import KpClient
from sqlalchemy.orm.attributes import flag_modified


def format_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("7") or digits.startswith("8"):
        digits = digits[1:]
    d = digits[:10]
    out = "+7"
    if len(d) > 0:
        out += f" ({d[:3]}"
    if len(d) >= 3:
        out += ")"
    if len(d) > 3:
        out += f" {d[3:6]}"
    if len(d) > 6:
        out += f"-{d[6:8]}"
    if len(d) > 8:
        out += f"-{d[8:10]}"
    return out


def normalize():
    all_clients = KpClient.query.all()
    touched = 0
    rows = 0
    for c in all_clients:
        contacts = c.contacts or []
        if not isinstance(contacts, list):
            continue
        changed = False
        new_contacts = []
        for item in contacts:
            if not isinstance(item, dict):
                new_contacts.append(item)
                continue
            old = (item.get("phone") or "").strip()
            if not old:
                new_contacts.append(item)
                continue
            new = format_phone(old)
            rows += 1
            if new != old:
                changed = True
                new_item = dict(item)
                new_item["phone"] = new
                new_contacts.append(new_item)
                print(f"  client {c.id}: {old!r} -> {new!r}", flush=True)
            else:
                new_contacts.append(item)
        if changed:
            c.contacts = new_contacts
            # JSONB — SQLAlchemy не видит мутацию внутренних элементов,
            # поэтому принудительно помечаем атрибут dirty.
            flag_modified(c, "contacts")
            touched += 1

    if touched:
        db.session.commit()
    print(
        f"\nИтог: обработано клиентов={len(all_clients)}, "
        f"телефонов={rows}, нормализовано={touched} клиентов (как минимум 1 телефон изменён)",
        flush=True,
    )


if __name__ == "__main__":
    with app.app_context():
        normalize()
    print("Done.", flush=True)
