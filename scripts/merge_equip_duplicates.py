"""
Разовое слияние дубликатов категорий, порождённых старым Equip-скриптом
(slug вида `<translit>-eq<equip_id>`, name КАПСОМ, рядом уже есть
«нормальная» категория с тем же именем).

Логика: `merge_exact_duplicates` из routes/category_aliases.py уже
умеет ровно то что нужно — итеративно находит группы категорий с
одинаковым (parent_id, LOWER(name)) и сливает каждую группу в
target (max products_count, при равенстве — min id). Товары / alias'ы /
дети / связи с header/homepage/search переносятся, картинки склеиваются.

Скрипт — тонкая обёртка, которая:
  1) Нормализует имя ВСЕХ категорий через utils.category_normalize
     (иначе `ВЕСЫ БЫТОВЫЕ` и `Весы бытовые` останутся раздельными
     ключами — `.lower()` в find_groups это уравняет, но чтобы после
     merge master получил уже нормализованное имя, а не капс из Equip,
     нормализуем ДО).
  2) Прогоняет merge_exact_duplicates.
  3) Печатает отчёт.

Dry-run по умолчанию (rollback в конце); реально применить: --apply.

Запуск (Render Job):
    python -u -m scripts.merge_equip_duplicates          # dry-run
    python -u -m scripts.merge_equip_duplicates --apply  # применить
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func

from app import app
from extensions import db
from models.category import Category
from models.product import Product
from routes.category_aliases import _merge_categories_impl
from utils.category_normalize import normalize_name


def normalize_all_names():
    """Проходит по всем категориям и обновляет name через normalize_name,
    если результат отличается. Возвращает счётчик изменений."""
    changed = 0
    for c in Category.query.all():
        new_name = normalize_name(c.name)
        if new_name and new_name != c.name:
            c.name = new_name
            changed += 1
    db.session.flush()
    return changed


def merge_pass():
    """Один проход merge для дубликатов (parent_id, LOWER(name)).
    Возвращает (groups_merged, categories_removed, products_moved,
    aliases_relinked). Копия логики из merge_exact_duplicates —
    вынесена сюда, чтобы можно было прогнать под dry-run без HTTP."""
    from sqlalchemy import func as _f

    def find_groups():
        cats = Category.query.all()
        groups = defaultdict(list)
        for c in cats:
            key = (c.parent_id, (c.name or '').strip().lower())
            groups[key].append(c)
        return [(k, g) for k, g in groups.items() if len(g) >= 2]

    total_groups = 0
    total_removed = 0
    total_products = 0
    total_aliases = 0
    passes = 0
    MAX_PASSES = 20

    while True:
        duplicate_groups = find_groups()
        if not duplicate_groups:
            break
        passes += 1
        if passes > MAX_PASSES:
            print(f'⚠️  Merge не сошёлся за {MAX_PASSES} проходов — прерываю')
            break

        counts_rows = db.session.query(Product.category_id, _f.count(Product.id)).group_by(Product.category_id).all()
        counts = {cid: cnt for cid, cnt in counts_rows}

        for _key, group in duplicate_groups:
            group_sorted = sorted(group, key=lambda c: (-counts.get(c.id, 0), c.id))
            target = group_sorted[0]
            sources = group_sorted[1:]
            for src in sources:
                # Логируем что сливаем — чтобы в отчёте было видно.
                print(f'  merge: [id={src.id:5d}] {src.slug!r} → [id={target.id:5d}] {target.slug!r}')
                result = _merge_categories_impl(src.id, target.id)
                total_products += result['products_moved']
                total_aliases += result['aliases_relinked']
                total_removed += 1
            total_groups += 1

        db.session.flush()

    return total_groups, total_removed, total_products, total_aliases, passes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='реально применить; без флага — dry-run (rollback)')
    args = parser.parse_args()

    with app.app_context():
        print('=' * 70)
        eq_before = Category.query.filter(Category.slug.op('~')(r'-eq[0-9]+$')).count()
        total_before = Category.query.count()
        print(f'Всего категорий:      {total_before}')
        print(f'С суффиксом -eq<N>:   {eq_before}')
        print('-' * 70)

        print('Шаг 1: нормализация имён категорий (капс → «Первая заглавная»)')
        renamed = normalize_all_names()
        print(f'  переименовано: {renamed}')
        print('-' * 70)

        print('Шаг 2: merge дубликатов (parent_id, LOWER(name))')
        groups, removed, products, aliases, passes = merge_pass()
        print('-' * 70)
        print(f'Групп смерджено:       {groups}')
        print(f'Категорий удалено:     {removed}')
        print(f'Товаров перепривязано: {products}')
        print(f'Алиасов перепривязано: {aliases}')
        print(f'Проходов:              {passes}')
        print('-' * 70)

        eq_after = Category.query.filter(Category.slug.op('~')(r'-eq[0-9]+$')).count()
        total_after = Category.query.count()
        print(f'Всего категорий после: {total_after}')
        print(f'С -eq<N> после:        {eq_after}')

        print('=' * 70)
        if args.apply:
            db.session.commit()
            print('✅ Изменения применены.')
        else:
            db.session.rollback()
            print('⚠️  DRY-RUN: изменения НЕ применены. Запустите с --apply.')


if __name__ == '__main__':
    main()
