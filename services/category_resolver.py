"""
Резолвинг категорий из внешних поставщиков в наши канонич. категории.

Основная точка входа — `resolve_category_path(source, path)` — принимает
список имён от корня до листа (как приходит из воркера BIO/Equip) и
возвращает id листовой канонич. категории. Дерево создаётся при
необходимости; повторные вызовы с тем же path идут через таблицу
`category_alias` и мгновенно попадают в тот же id.

Алгоритм для каждого уровня (`_resolve_one`):
  1) `category_alias` (source, parent_id, LOWER(name)) → hit
  2) точное совпадение по `Category.name` (LOWER, тот же parent_id) →
     создаём alias `is_auto=true`, hit
  3) fuzzy-совпадение (SequenceMatcher ratio > 0.85) среди сиблингов
     под тем же parent_id → alias с `is_auto=true, needs_review=true`,
     hit (админ увидит в UI-фильтре «требует ревью» и подтвердит /
     переназначит)
  4) miss → создаём новую `Category` с нормализованным именем + alias
     `is_auto=true`

Все имена нормализуются через `utils.category_normalize.normalize_name`
(единая точка правды для регистра / аббревиатур).

Резолвер идемпотентен и потокобезопасен на уровне транзакции: коммит
делает вызывающий код (обычно endpoint создания товара). Внутри —
только `db.session.add()` / `db.session.flush()`, чтобы получить id
без коммита.
"""

from difflib import SequenceMatcher
from typing import Iterable, Optional

from sqlalchemy import func

from extensions import db
from models.category import Category
from models.category_alias import CategoryAlias
from utils.category_normalize import normalize_name


# Порог fuzzy-совпадения (0..1). Выше = строже. 0.85 подобрано эмпирически:
# «Пароконвектоматы» vs «Параконвектоматные аппараты» ≈ 0.75 — не тригерит
# автомерж (это правильно, разные семантически близкие имена лучше пусть
# админ смерджит вручную), а «Пароконвектоматы» vs «пароконвектомат» ≈
# 0.90 — тригерит (это опечатка/форма).
FUZZY_THRESHOLD = 0.85


def _slug_for_category(name: str) -> str:
    """
    Тонкая обёртка над существующим `safe_slugify` из routes/products.py —
    чтобы у категорий и товаров была одна и та же логика транслитерации.
    Импорт локальный, чтобы не тащить routes в services (циркулярная
    зависимость через blueprint).
    """
    from routes.products import safe_slugify
    return safe_slugify(name)


def _ensure_unique_slug(base: str) -> str:
    """Добавляет `-2`, `-3`, ... если base уже занят другой категорией."""
    if not base:
        return base
    candidate = base
    n = 2
    while Category.query.filter_by(slug=candidate).first() is not None:
        candidate = f'{base}-{n}'
        n += 1
    return candidate


def _find_alias(source: Optional[str], parent_id: Optional[int], name: str) -> Optional[CategoryAlias]:
    """Ищет alias case-insensitive по (source, parent_id, alias_name)."""
    q = CategoryAlias.query.filter(
        func.lower(CategoryAlias.alias_name) == name.lower()
    )
    q = q.filter(CategoryAlias.source.is_(None) if source is None else CategoryAlias.source == source)
    q = q.filter(CategoryAlias.parent_id.is_(None) if parent_id is None else CategoryAlias.parent_id == parent_id)
    return q.first()


def _find_alias_any_source(parent_id: Optional[int], name: str) -> Optional[CategoryAlias]:
    """
    Fallback-поиск alias БЕЗ учёта source — если один поставщик уже
    завёл эту категорию, второй поставщик с таким же именем пусть тоже
    попадает туда (не создаёт дубликат под другим source).
    """
    q = CategoryAlias.query.filter(
        func.lower(CategoryAlias.alias_name) == name.lower()
    )
    q = q.filter(CategoryAlias.parent_id.is_(None) if parent_id is None else CategoryAlias.parent_id == parent_id)
    return q.first()


def _find_category_exact(parent_id: Optional[int], name: str) -> Optional[Category]:
    """Точное совпадение по имени (case-insensitive) среди сиблингов."""
    q = Category.query.filter(func.lower(Category.name) == name.lower())
    q = q.filter(Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id)
    return q.first()


def _find_category_fuzzy(parent_id: Optional[int], name: str) -> Optional[Category]:
    """
    Fuzzy-поиск: SequenceMatcher.ratio() к каждой сиблинг-категории.
    Возвращаем лучшее совпадение выше FUZZY_THRESHOLD, иначе None.
    """
    q = Category.query
    q = q.filter(Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id)
    siblings = q.all()
    if not siblings:
        return None
    target = name.lower()
    best: Optional[Category] = None
    best_ratio = 0.0
    for cat in siblings:
        r = SequenceMatcher(None, cat.name.lower(), target).ratio()
        if r > best_ratio:
            best_ratio = r
            best = cat
    if best_ratio >= FUZZY_THRESHOLD:
        return best
    return None


def _create_category(parent_id: Optional[int], normalized_name: str) -> Category:
    """
    Создаёт новую Category с уникальным slug'ом. Не коммитит — только
    flush, чтобы получить id для дальнейшего создания alias'ов.
    """
    slug_base = _slug_for_category(normalized_name)
    slug = _ensure_unique_slug(slug_base)
    cat = Category(
        name=normalized_name,
        slug=slug,
        parent_id=parent_id,
        show_in_menu=True,
    )
    db.session.add(cat)
    db.session.flush()
    return cat


def _create_alias(
    source: Optional[str],
    parent_id: Optional[int],
    alias_name: str,
    category_id: int,
    is_auto: bool = True,
    needs_review: bool = False,
) -> CategoryAlias:
    """
    Создаёт alias-запись. При race-condition (второй параллельный
    воркер уже создал такой же) db поймает UniqueConstraint и вызывающий
    поймает IntegrityError — на practice race редкая, workers сериализованы.
    """
    alias = CategoryAlias(
        source=source,
        parent_id=parent_id,
        alias_name=alias_name,
        category_id=category_id,
        is_auto=is_auto,
        needs_review=needs_review,
    )
    db.session.add(alias)
    db.session.flush()
    return alias


def _resolve_one(source: Optional[str], parent_id: Optional[int], raw_name: str) -> int:
    """
    Резолвит одно имя категории в id. См. docstring модуля — 4 шага
    fallback'а. Возвращает category_id.
    """
    name = (raw_name or '').strip()
    if not name:
        raise ValueError('resolve_category: пустое имя категории')

    # 1) alias с точным source
    alias = _find_alias(source, parent_id, name)
    if alias is not None:
        return alias.category_id

    # 1b) alias с любым source (в т.ч. вручную созданный админом или
    # seed при миграции существующих категорий) — чтобы не плодить
    # дубликаты для разных поставщиков.
    if source is not None:
        alias = _find_alias_any_source(parent_id, name)
        if alias is not None:
            # Регистрируем этот source тоже — в следующий раз найдём сразу
            # на шаге 1.
            _create_alias(source, parent_id, name, alias.category_id, is_auto=True)
            return alias.category_id

    # 2) точное совпадение по имени category (case-insensitive)
    normalized = normalize_name(name)
    cat = _find_category_exact(parent_id, normalized)
    if cat is not None:
        _create_alias(source, parent_id, name, cat.id, is_auto=True)
        return cat.id

    # 3) fuzzy среди сиблингов
    cat = _find_category_fuzzy(parent_id, normalized)
    if cat is not None:
        _create_alias(source, parent_id, name, cat.id, is_auto=True, needs_review=True)
        return cat.id

    # 4) miss → создаём новую
    new_cat = _create_category(parent_id, normalized)
    _create_alias(source, parent_id, name, new_cat.id, is_auto=True)
    return new_cat.id


def resolve_category_path(source: Optional[str], path: Iterable[str]) -> int:
    """
    Резолвит цепочку имён категорий от корня до листа в id листовой
    категории. Каждый уровень идёт через `_resolve_one` с parent_id
    предыдущего уровня. Пустые элементы пропускаются.

    Пример:
        resolve_category_path('bio', ['Оборудование', 'Тепловое', 'Пароконвектоматы'])

    Возвращает category_id последнего уровня. Не коммитит — вызывающий
    код (обычно create_product) сам делает db.session.commit().
    """
    parent_id: Optional[int] = None
    last_id: Optional[int] = None
    for raw_name in path:
        name = (raw_name or '').strip()
        if not name:
            continue
        last_id = _resolve_one(source, parent_id, name)
        parent_id = last_id
    if last_id is None:
        raise ValueError('resolve_category_path: пустой путь категории')
    return last_id
