"""
Разово: засеять в maintenance_notice 4 типовые заготовки на разные
ситуации (технические работы, тех. сбой, крупное обновление,
профилактика ночью), чтобы owner мог сразу выбирать из готового
списка (в веб-админке или в Android-виджете), а не писать с нуля.

Идемпотентно: если заготовка с таким же `title` уже есть — пропускаем.

Запуск:
    python -u -m migrations.seed_maintenance_notices
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db

from models.maintenance import MaintenanceNotice


SEEDS = [
    (
        "Технические работы",
        "Проводим обновление сайта. Вернёмся в ближайшее время. "
        "Для срочных заказов и консультаций — звоните по номеру в контактах, "
        "или напишите в WhatsApp.",
    ),
    (
        "Технический сбой",
        "У нас временные неполадки — уже устраняем. Приносим извинения за неудобства. "
        "Повторите визит через 10–15 минут, или свяжитесь напрямую через WhatsApp.",
    ),
    (
        "Крупное обновление сайта",
        "Готовим большое обновление: новый каталог, удобный поиск, свежие разделы. "
        "Сайт недоступен несколько часов. По любым вопросам — звоните в контакты.",
    ),
    (
        "Профилактика ночью",
        "Профилактические работы на сайте с 23:00 до 06:00. Утром всё снова работает. "
        "Срочные заказы — через WhatsApp.",
    ),
]


def apply():
    print(f'Seeding maintenance_notice ({len(SEEDS)} шаблонов)…', flush=True)
    existing_titles = {
        row.title.strip().lower()
        for row in MaintenanceNotice.query.all()
    }
    added = skipped = 0
    for title, body in SEEDS:
        if title.strip().lower() in existing_titles:
            print(f'  = уже есть: {title!r}', flush=True)
            skipped += 1
            continue
        db.session.add(MaintenanceNotice(title=title, body=body))
        print(f'  + добавлено: {title!r}', flush=True)
        added += 1
    if added:
        db.session.commit()
    print('', flush=True)
    print(f'OK: добавлено {added}, пропущено (дубли) {skipped}', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
    print('Done.', flush=True)
