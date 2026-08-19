"""
Одноразовая (в идеале) миграция существующих категорий:

  1. Нормализует `Category.name` через `utils.category_normalize.normalize_name`
     (первая буква заглавная, остальные строчные; аббревиатуры POS/USB/WiFi/...
     остаются как есть). Пересобирает `slug` через тот же safe_slugify,
     что используется в остальном коде, с уникализацией.
  2. Создаёт seed-запись `CategoryAlias(source=NULL, alias_name=<original>,
     category_id=<this>)` для каждой существующей категории — чтобы если
     bio/equip снова пришлёт со старым капсом, оно попало через alias
     в эту же категорию, а не создало новую.
  3. Опционально (`--merge-duplicates`) — автомерж категорий, которые
     после нормализации оказываются одинаковыми `(parent_id, name)`:
     все товары / aliases / дети / картинки переносятся в «target»
     (categoria с большим числом товаров, при равенстве — меньший id),
     source-категории удаляются.

По умолчанию — DRY-RUN (только показывает что бы сделал). Реальные
изменения только с `--apply`. `--merge-duplicates` без `--apply` тоже
только показывает план мерджа.

Требует уже применённую миграцию `apply_category_alias` (таблица
`category_alias` должна существовать).

Запуск (Render Shell или локально):
    cd pospro_new_server
    python -u -m scripts.normalize_categories                   # dry-run
    python -u -m scripts.normalize_categories --apply           # применить
    python -u -m scripts.normalize_categories --apply --merge-duplicates
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, text

from app import app
from extensions import db
from models.category import Category
from models.category_alias import CategoryAlias
from models.product import Product
from utils.category_normalize import normalize_name


def _slug_for(name):
    """Единый источник транслитерации — как в products.safe_slugify."""
    from routes.products import safe_slugify
    return safe_slugify(name)


def _ensure_unique_slug(base, exclude_id=None):
    if not base:
        return base
    candidate = base
    n = 2
    while True:
        q = Category.query.filter_by(slug=candidate)
        if exclude_id is not None:
            q = q.filter(Category.id != exclude_id)
        if q.first() is None:
            return candidate
        candidate = f'{base}-{n}'
        n += 1


def _count_products(category_id):
    return db.session.query(func.count(Product.id)).filter(Product.category_id == category_id).scalar() or 0


def _plan_renames():
    """
    Строит план изменений для каждой категории:
      { id: {old_name, new_name, old_slug, new_slug, changed: bool} }
    """
    plan = {}
    for cat in Category.query.order_by(Category.id).all():
        new_name = normalize_name(cat.name)
        base_slug = _slug_for(new_name)
        # Уникальность slug'а сверим уже в apply — сейчас просто фиксируем
        # желаемый базовый.
        changed = new_name != cat.name or base_slug != cat.slug
        plan[cat.id] = {
            'old_name': cat.name,
            'new_name': new_name,
            'old_slug': cat.slug,
            'new_slug_base': base_slug,
            'changed': changed,
            'parent_id': cat.parent_id,
        }
    return plan


def _plan_duplicates(plan):
    """
    Группирует категории по `(parent_id, normalized_name.lower())` — где
    в группе > 1 записи, это дубликат кандидат на merge. Возвращает
    список групп: [{key, ids: [...], target_id, sources: [...]}], где
    target — с большим кол-вом товаров.
    """
    groups = defaultdict(list)
    for cid, info in plan.items():
        key = (info['parent_id'], info['new_name'].lower())
        groups[key].append(cid)

    duplicates = []
    for key, ids in groups.items():
        if len(ids) < 2:
            continue
        # Выбираем target: max(products_count), при равенстве min(id)
        counts = [(cid, _count_products(cid)) for cid in ids]
        counts.sort(key=lambda x: (-x[1], x[0]))
        target_id = counts[0][0]
        sources = [cid for cid in ids if cid != target_id]
        duplicates.append({
            'key': key,
            'name': plan[ids[0]]['new_name'],
            'parent_id': key[0],
            'target_id': target_id,
            'target_count': counts[0][1],
            'sources': sources,
            'source_counts': dict((cid, c) for cid, c in counts if cid != target_id),
        })
    return duplicates


def _print_plan(plan, duplicates, existing_aliases):
    print('=== План изменений ===')
    changed = [(cid, info) for cid, info in plan.items() if info['changed']]
    print(f'  Категорий всего: {len(plan)}')
    print(f'  Требуют переименования / пересборки slug: {len(changed)}')
    for cid, info in changed[:30]:
        print(f'    #{cid:>4}  {info["old_name"]!r}  →  {info["new_name"]!r}  (slug: {info["old_slug"]!r} → {info["new_slug_base"]!r})')
    if len(changed) > 30:
        print(f'    ... и ещё {len(changed) - 30}')

    print()
    print(f'  Seed-алиасов будет создано: {len([1 for cid, info in plan.items() if cid not in existing_aliases])}')
    print(f'    (у {len(existing_aliases)} категорий seed-alias уже есть)')

    print()
    if duplicates:
        print(f'  Обнаружено групп дубликатов: {len(duplicates)}')
        for d in duplicates:
            parent = d['parent_id']
            parent_str = f'parent#{parent}' if parent else '<root>'
            print(f'    [{parent_str}] "{d["name"]}"')
            print(f'      target: #{d["target_id"]} ({d["target_count"]} товаров)')
            for sid in d['sources']:
                print(f'      merge:  #{sid} ({d["source_counts"][sid]} товаров) → #{d["target_id"]}')
    else:
        print('  Дубликатов не найдено.')


def _apply_renames(plan):
    """
    Меняет name/slug у категорий согласно plan. Для slug — обеспечивает
    уникальность, но с учётом, что после переименования другая категория
    может освободить старый slug.
    """
    # Сортируем по убыванию длины старого slug — чтобы освободить длинные
    # раньше и переиспользовать короткие. Не критично, обычно UNIQUE-заявка
    # разрулится через `-2` суффикс.
    changed_ids = [cid for cid, info in plan.items() if info['changed']]
    print(f'Применяю переименование / slug для {len(changed_ids)} категорий...', flush=True)
    for cid in changed_ids:
        info = plan[cid]
        cat = Category.query.get(cid)
        if cat is None:
            continue
        cat.name = info['new_name']
        new_slug = _ensure_unique_slug(info['new_slug_base'], exclude_id=cid)
        cat.slug = new_slug
    db.session.flush()


def _apply_seed_aliases(plan, existing_aliases):
    """
    Для каждой категории, у которой ещё нет seed-alias (source=NULL,
    alias_name=<original>), создаём такую запись — чтобы старые названия
    от поставщика продолжали резолвиться в эту же категорию.
    """
    to_create = []
    for cid, info in plan.items():
        if cid in existing_aliases:
            continue
        cat = Category.query.get(cid)
        if cat is None:
            continue
        alias = CategoryAlias(
            source=None,
            parent_id=cat.parent_id,
            alias_name=info['old_name'],
            category_id=cid,
            is_auto=False,
            needs_review=False,
        )
        to_create.append(alias)
    print(f'Создаю seed-алиасов: {len(to_create)}...', flush=True)
    for a in to_create:
        db.session.add(a)
    db.session.flush()


def _merge_pair(source_id, target_id):
    """
    Переносит всё из source в target и удаляет source. НЕ коммитит —
    вызывающий обёртывает пачку мерджей в одну транзакцию.

    Что переносится:
      - products.category_id     : source → target
      - category_alias.category_id: source → target  (алиасы, указывавшие на source)
      - category_alias.parent_id  : source → target  (алиасы, у которых родитель = source)
      - category.parent_id (дети): source → target
      - header_menu_items.category_id: source → target
      - homepage_categories.category_id: source → target
      - search_page_categories: если у target нет — переприсваиваем, иначе удаляем source-запись
      - image_url: если у target пустой, а у source есть — переносим
    """
    src = Category.query.get(source_id)
    tgt = Category.query.get(target_id)
    if src is None or tgt is None or src.id == tgt.id:
        return 0, 0

    # Картинка — переносим ДО перепривязки, чтобы файл остался.
    if not tgt.image_url and src.image_url:
        tgt.image_url = src.image_url
        src.image_url = None  # чтобы удаление src не тронуло файл

    # products.category_id
    prod_moved = db.session.execute(
        text('UPDATE product SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    ).rowcount or 0

    # category_alias.category_id — алиасы, ведущие в source, теперь ведут в target
    alias_relinked = db.session.execute(
        text('UPDATE category_alias SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    ).rowcount or 0

    # category_alias.parent_id — алиасы, у которых parent=source
    db.session.execute(
        text('UPDATE category_alias SET parent_id = :t WHERE parent_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # category.parent_id — дети source становятся детьми target
    db.session.execute(
        text('UPDATE category SET parent_id = :t WHERE parent_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # header_menu_items.category_id — есть CASCADE на удаление, но нам
    # нужен именно перенос, а не потеря.
    db.session.execute(
        text('UPDATE header_menu_items SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # homepage_categories.category_id (без FK-constraint)
    db.session.execute(
        text('UPDATE homepage_category SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # search_page_categories: UNIQUE constraint на category_id — если
    # target уже там, source-запись удаляем (иначе перепривязываем).
    tgt_has_sp = db.session.execute(
        text('SELECT 1 FROM search_page_category WHERE category_id = :t LIMIT 1'),
        {'t': target_id},
    ).first()
    if tgt_has_sp:
        db.session.execute(
            text('DELETE FROM search_page_category WHERE category_id = :s'),
            {'s': source_id},
        )
    else:
        db.session.execute(
            text('UPDATE search_page_category SET category_id = :t WHERE category_id = :s'),
            {'t': target_id, 's': source_id},
        )

    db.session.delete(src)
    db.session.flush()
    return prod_moved, alias_relinked


def _apply_merges(duplicates):
    total_prod = 0
    total_alias = 0
    for d in duplicates:
        for sid in d['sources']:
            print(f'  merge #{sid} → #{d["target_id"]} ("{d["name"]}")', flush=True)
            p, a = _merge_pair(sid, d['target_id'])
            total_prod += p
            total_alias += a
    return total_prod, total_alias


def _load_existing_seed_aliases():
    """
    Возвращает множество category_id, у которых уже есть seed-alias
    (source IS NULL) — чтобы не создавать дубликаты при повторном запуске.
    """
    rows = CategoryAlias.query.filter(CategoryAlias.source.is_(None)).with_entities(CategoryAlias.category_id).all()
    return set(r[0] for r in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Реально применить изменения (иначе dry-run)')
    parser.add_argument('--merge-duplicates', action='store_true', help='Дополнительно смерджить дубликаты автоматически')
    args = parser.parse_args()

    with app.app_context():
        plan = _plan_renames()
        existing_aliases = _load_existing_seed_aliases()
        duplicates = _plan_duplicates(plan)

        _print_plan(plan, duplicates, existing_aliases)

        if not args.apply:
            print()
            print('DRY-RUN: изменения не применены. Используйте --apply для реального запуска.')
            return

        print()
        print('=== APPLY ===', flush=True)
        try:
            _apply_renames(plan)
            _apply_seed_aliases(plan, existing_aliases)
            if args.merge_duplicates and duplicates:
                print(f'Мерджу групп дубликатов: {len(duplicates)}...', flush=True)
                prod_moved, alias_moved = _apply_merges(duplicates)
                print(f'  Товаров перенесено: {prod_moved}')
                print(f'  Алиасов перепривязано: {alias_moved}')
            elif duplicates:
                print(f'ВНИМАНИЕ: найдено {len(duplicates)} групп дубликатов — не смерджены (нет флага --merge-duplicates).')
                print('  Смерджите через админ UI или запустите с --merge-duplicates.')
            db.session.commit()
            print('OK', flush=True)
        except Exception:
            db.session.rollback()
            raise


if __name__ == '__main__':
    main()
