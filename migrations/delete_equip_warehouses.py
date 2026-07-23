"""
Разовая миграция: удалить 8 из 10 складов Equip, оставить только Москву и Алматы
(по решению руководства, 2026-07-24).

Что делает:
1. Собирает все Warehouse с именем в чёрном списке
2. Собирает product_id со всех PWC на этих складах (для последующего пересчёта min-price)
3. Удаляет склады → каскадом сносятся ProductWarehouseCost на них (см. модель)
4. Для каждого затронутого product_id вызывает _apply_min_price — пересчитывает
   product.price/supplier_id/quantity по оставшимся складам

Товары НЕ удаляются — по договорённости с юзером. Если товар был ТОЛЬКО на удалённом
складе, product.price станет 0 (нет ни одного calculated_price > 0), продукт
останется висеть на витрине без цены до появления новых складов.

Идемпотентна: повторный запуск не найдёт складов из чёрного списка и завершится с 0 удалений.

Запуск (Render Shell или локально с DATABASE_URL):
    cd pospro_new_server
    python -m migrations.delete_equip_warehouses
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from models.warehouse import Warehouse
from models.product_warehouse_cost import ProductWarehouseCost
from routes.product_costs import _apply_min_price


# Полные названия складов на удаление. Оставляем только «Equip Москва» и «Equip Алматы».
BLACKLIST_NAMES = [
    "Equip Санкт-Петербург",
    "Equip Екатеринбург",
    "Equip Краснодар",
    "Equip Новосибирск",
    "Equip Ростов-на-Дону",
    "Equip Самара",
    "Equip Владивосток",
    "Equip Волжский",
]


def delete_equip_warehouses():
    warehouses = Warehouse.query.filter(Warehouse.name.in_(BLACKLIST_NAMES)).all()

    if not warehouses:
        print(f'Не найдено ни одного склада из чёрного списка ({len(BLACKLIST_NAMES)} имён).')
        print('Возможно, миграция уже была запущена ранее. Ничего не делаю.')
        return True

    print(f'Найдено складов на удаление: {len(warehouses)}')
    for w in warehouses:
        print(f'  [{w.id:>4}] {w.name!r}')

    # 1. Собрать все product_id которые лежат на удаляемых складах.
    #    После каскадного удаления PWC потеряются, но product.price останется
    #    ссылаться на удалённый склад через product.supplier_id — надо
    #    пересчитать min-price по оставшимся PWC.
    warehouse_ids = [w.id for w in warehouses]
    affected_product_ids = set(
        pid for (pid,) in db.session.query(ProductWarehouseCost.product_id)
        .filter(ProductWarehouseCost.warehouse_id.in_(warehouse_ids))
        .distinct()
        .all()
    )
    print(f'\nЗатронуто товаров (лежали на удаляемых складах): {len(affected_product_ids)}')

    # 2. Удалить склады. cascade='all, delete-orphan' в модели снесёт PWC.
    for w in warehouses:
        db.session.delete(w)
    db.session.flush()  # применить удаления перед _apply_min_price

    # 3. Пересчитать min-price для затронутых товаров.
    #    _apply_min_price пробегает по всем оставшимся PWC товара и выбирает
    #    минимальный calculated_price среди складов с quantity > 0.
    #    Если ни одного PWC не осталось (товар был только на удалённых
    #    складах) — product.price/quantity останутся как есть.
    recalced = 0
    errors = 0
    for pid in affected_product_ids:
        try:
            _apply_min_price(pid)
            recalced += 1
        except Exception as exc:
            errors += 1
            print(f'  [pid={pid}] _apply_min_price ошибка: {exc}')

    db.session.commit()

    print('\n=== ИТОГИ ===')
    print(f'  Удалено складов:          {len(warehouses)}')
    print(f'  Пересчитано товаров:      {recalced}')
    print(f'  Ошибок пересчёта:         {errors}')
    return errors == 0


if __name__ == '__main__':
    with app.app_context():
        ok = delete_equip_warehouses()
        sys.exit(0 if ok else 1)
