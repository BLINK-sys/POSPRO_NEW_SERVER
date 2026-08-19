"""
Admin API для управления системой алиасов категорий (см.
`services/category_resolver.py`, модель `models/category_alias.py`).

Все endpoints требуют JWT с ролью admin/system.

- GET    /api/admin/category-aliases                     — список с фильтрами
- POST   /api/admin/category-aliases                     — создать вручную
- PUT    /api/admin/category-aliases/<id>                — сменить category_id / needs_review
- DELETE /api/admin/category-aliases/<id>                — удалить
- POST   /api/admin/categories/merge                     — merge двух категорий
- GET    /api/admin/categories/find-similar              — pair-wise fuzzy предложения
"""

from difflib import SequenceMatcher

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func, text

from extensions import db
from models.category import Category
from models.category_alias import CategoryAlias
from models.product import Product


category_aliases_bp = Blueprint('category_aliases', __name__)


def _check_admin():
    jwt_data = get_jwt()
    return jwt_data.get('role') in ('admin', 'system')


def _category_dict(cat):
    return {
        'id': cat.id,
        'name': cat.name,
        'slug': cat.slug,
        'parent_id': cat.parent_id,
    }


def _alias_dict(alias, category=None):
    d = alias.to_dict()
    if category is not None:
        d['category'] = _category_dict(category)
    else:
        # Ленивая догрузка если не передали.
        cat = Category.query.get(alias.category_id)
        d['category'] = _category_dict(cat) if cat else None
    return d


# ============ Алиасы: CRUD ============

@category_aliases_bp.route('/category-aliases', methods=['GET'])
@jwt_required()
def list_aliases():
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    q = CategoryAlias.query
    source = request.args.get('source')
    needs_review = request.args.get('needs_review')
    is_auto = request.args.get('is_auto')
    category_id = request.args.get('category_id', type=int)
    search = (request.args.get('q') or '').strip()

    if source:
        if source == 'manual':
            q = q.filter(CategoryAlias.source.is_(None))
        else:
            q = q.filter(CategoryAlias.source == source)
    if needs_review in ('1', 'true', 'yes'):
        q = q.filter(CategoryAlias.needs_review.is_(True))
    if is_auto in ('1', 'true', 'yes'):
        q = q.filter(CategoryAlias.is_auto.is_(True))
    if category_id:
        q = q.filter(CategoryAlias.category_id == category_id)
    if search:
        q = q.filter(func.lower(CategoryAlias.alias_name).like(f'%{search.lower()}%'))

    aliases = q.order_by(CategoryAlias.needs_review.desc(), CategoryAlias.created_at.desc()).limit(500).all()

    # Батчево догружаем категории (чтобы не делать N+1)
    cat_ids = {a.category_id for a in aliases}
    cats_by_id = {c.id: c for c in Category.query.filter(Category.id.in_(cat_ids)).all()} if cat_ids else {}

    return jsonify({
        'items': [_alias_dict(a, cats_by_id.get(a.category_id)) for a in aliases],
        'total': len(aliases),
    })


@category_aliases_bp.route('/category-aliases', methods=['POST'])
@jwt_required()
def create_alias():
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    data = request.json or {}
    alias_name = (data.get('alias_name') or '').strip()
    category_id = data.get('category_id')
    source = data.get('source') or None  # 'bio' / 'equip' / None (manual)
    parent_id = data.get('parent_id') or None

    if not alias_name:
        return jsonify({'error': 'alias_name обязателен'}), 400
    if not category_id:
        return jsonify({'error': 'category_id обязателен'}), 400

    cat = Category.query.get(category_id)
    if not cat:
        return jsonify({'error': 'Категория не найдена'}), 404

    # Проверка дубликата (UniqueConstraint, но заранее по-человечески)
    existing = CategoryAlias.query.filter(
        CategoryAlias.source.is_(None) if source is None else CategoryAlias.source == source,
        CategoryAlias.parent_id.is_(None) if parent_id is None else CategoryAlias.parent_id == parent_id,
        func.lower(CategoryAlias.alias_name) == alias_name.lower(),
    ).first()
    if existing:
        return jsonify({'error': 'Такой алиас уже существует', 'existing_id': existing.id}), 409

    alias = CategoryAlias(
        source=source,
        parent_id=parent_id,
        alias_name=alias_name,
        category_id=category_id,
        is_auto=False,
        needs_review=False,
    )
    db.session.add(alias)
    db.session.commit()
    return jsonify(_alias_dict(alias, cat)), 201


@category_aliases_bp.route('/category-aliases/<int:alias_id>', methods=['PUT'])
@jwt_required()
def update_alias(alias_id):
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    alias = CategoryAlias.query.get_or_404(alias_id)
    data = request.json or {}

    # Разрешаем менять: category_id (переназначение), needs_review (подтверждение)
    if 'category_id' in data:
        new_cat = Category.query.get(data['category_id'])
        if not new_cat:
            return jsonify({'error': 'Категория не найдена'}), 404
        alias.category_id = new_cat.id
    if 'needs_review' in data:
        alias.needs_review = bool(data['needs_review'])

    db.session.commit()
    return jsonify(_alias_dict(alias))


@category_aliases_bp.route('/category-aliases/<int:alias_id>', methods=['DELETE'])
@jwt_required()
def delete_alias(alias_id):
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    alias = CategoryAlias.query.get_or_404(alias_id)
    db.session.delete(alias)
    db.session.commit()
    return jsonify({'success': True})


# ============ Merge категорий ============

def _merge_categories_impl(source_id, target_id):
    """
    Транзакционный merge категории source → target.
    См. `scripts/normalize_categories._merge_pair` — та же логика.
    Возвращает {products_moved, aliases_relinked}.
    """
    src = Category.query.get(source_id)
    tgt = Category.query.get(target_id)
    if src is None or tgt is None:
        raise ValueError('Категория не найдена')
    if src.id == tgt.id:
        raise ValueError('Нельзя смерджить категорию саму в себя')

    # Картинка — до перепривязки
    if not tgt.image_url and src.image_url:
        tgt.image_url = src.image_url
        src.image_url = None

    products_moved = db.session.execute(
        text('UPDATE product SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    ).rowcount or 0

    aliases_relinked = db.session.execute(
        text('UPDATE category_alias SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    ).rowcount or 0

    # Алиасы, у которых parent = source, теперь parent = target
    db.session.execute(
        text('UPDATE category_alias SET parent_id = :t WHERE parent_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # Дети source становятся детьми target
    db.session.execute(
        text('UPDATE category SET parent_id = :t WHERE parent_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # header_menu_items.category_id (перенос, не потеря)
    db.session.execute(
        text('UPDATE header_menu_items SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # homepage_categories.category_id (без FK-constraint)
    db.session.execute(
        text('UPDATE homepage_categories SET category_id = :t WHERE category_id = :s'),
        {'t': target_id, 's': source_id},
    )

    # search_page_categories имеет UNIQUE(category_id) — если target уже там,
    # source-запись удаляем; иначе перепривязываем.
    tgt_has_sp = db.session.execute(
        text('SELECT 1 FROM search_page_categories WHERE category_id = :t LIMIT 1'),
        {'t': target_id},
    ).first()
    if tgt_has_sp:
        db.session.execute(
            text('DELETE FROM search_page_categories WHERE category_id = :s'),
            {'s': source_id},
        )
    else:
        db.session.execute(
            text('UPDATE search_page_categories SET category_id = :t WHERE category_id = :s'),
            {'t': target_id, 's': source_id},
        )

    db.session.delete(src)
    return {'products_moved': products_moved, 'aliases_relinked': aliases_relinked}


@category_aliases_bp.route('/categories/merge-exact-duplicates', methods=['POST'])
@jwt_required()
def merge_exact_duplicates():
    """
    Автомерж всех групп категорий, где после нормализации `(parent_id,
    LOWER(name))` совпадают у нескольких категорий. Правило выбора
    target'а: **max(products_count), при равенстве min(id)** — товары
    сохраняются на месте, идентификатор остаётся стабильным.

    Всё в одной транзакции. Возвращает статистику: сколько групп
    смерджилось, сколько категорий удалено, сколько товаров / алиасов
    перепривязано.

    Использовать когда админ хочет быстро схлопнуть очевидные дубли
    после нормализации имён (например «ОБОРУДОВАНИЕ КОНДИТЕРСКОЕ» и
    «Оборудование кондитерское» — после нормализации оба
    «Оборудование кондитерское» с разными id). Fuzzy-совпадения
    здесь НЕ трогаются — только точное совпадение имени.
    """
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    from collections import defaultdict
    from sqlalchemy import func as _f

    cats = Category.query.all()
    groups = defaultdict(list)
    for c in cats:
        key = (c.parent_id, (c.name or '').strip().lower())
        groups[key].append(c)

    duplicate_groups = [(k, ids) for k, ids in groups.items() if len(ids) >= 2]
    if not duplicate_groups:
        return jsonify({'success': True, 'groups_merged': 0, 'categories_removed': 0, 'products_moved': 0, 'aliases_relinked': 0})

    # Считаем количество товаров пачкой — чтобы не дёргать в цикле.
    counts_rows = db.session.query(Product.category_id, _f.count(Product.id)).group_by(Product.category_id).all()
    counts = {cid: cnt for cid, cnt in counts_rows}

    total_removed = 0
    total_products = 0
    total_aliases = 0

    try:
        for _key, group in duplicate_groups:
            # target: max products, tiebreaker min(id)
            group_sorted = sorted(group, key=lambda c: (-counts.get(c.id, 0), c.id))
            target = group_sorted[0]
            sources = group_sorted[1:]
            for src in sources:
                result = _merge_categories_impl(src.id, target.id)
                total_products += result['products_moved']
                total_aliases += result['aliases_relinked']
                total_removed += 1
        db.session.commit()
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        return jsonify({'error': f'Ошибка при автомерже: {e}'}), 500

    return jsonify({
        'success': True,
        'groups_merged': len(duplicate_groups),
        'categories_removed': total_removed,
        'products_moved': total_products,
        'aliases_relinked': total_aliases,
    })


@category_aliases_bp.route('/categories/merge', methods=['POST'])
@jwt_required()
def merge_categories():
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    data = request.json or {}
    source_id = data.get('source_id') or data.get('from_id')
    target_id = data.get('target_id') or data.get('to_id')

    if not source_id or not target_id:
        return jsonify({'error': 'source_id и target_id обязательны'}), 400

    try:
        result = _merge_categories_impl(source_id, target_id)
        db.session.commit()
        return jsonify({'success': True, **result})
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        return jsonify({'error': f'Ошибка при merge: {e}'}), 500


# ============ Похожие категории (fuzzy pairs) ============

@category_aliases_bp.route('/categories/find-similar', methods=['GET'])
@jwt_required()
def find_similar():
    """
    Возвращает пары категорий с ratio > threshold (по умолчанию 0.85),
    у которых один и тот же parent_id. По умолчанию — только среди
    сиблингов, чтобы не предлагать мерджить категории из разных веток
    дерева. `threshold` регулируется параметром запроса.

    Пары в результате — по одной (a.id < b.id).
    """
    if not _check_admin():
        return jsonify({'error': 'Доступ запрещён'}), 403

    threshold = request.args.get('threshold', type=float) or 0.85

    cats = Category.query.order_by(Category.parent_id, Category.name).all()
    # Считаем продукты пачкой (для UI — сколько товаров в каждой)
    counts_rows = db.session.query(Product.category_id, func.count(Product.id)).group_by(Product.category_id).all()
    counts = {cid: cnt for cid, cnt in counts_rows}

    # Группируем по parent_id
    by_parent = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)

    pairs = []
    for parent_id, siblings in by_parent.items():
        for i in range(len(siblings)):
            for j in range(i + 1, len(siblings)):
                a, b = siblings[i], siblings[j]
                ratio = SequenceMatcher(None, a.name.lower(), b.name.lower()).ratio()
                if ratio >= threshold:
                    pairs.append({
                        'a': {**_category_dict(a), 'products_count': counts.get(a.id, 0)},
                        'b': {**_category_dict(b), 'products_count': counts.get(b.id, 0)},
                        'ratio': round(ratio, 3),
                        'parent_id': parent_id,
                    })

    pairs.sort(key=lambda p: p['ratio'], reverse=True)
    return jsonify({'items': pairs, 'total': len(pairs), 'threshold': threshold})
