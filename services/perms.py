"""
CRM-права для SystemUser: is_owner + новые флаги видимости/управления.

Живут в БД (system_users.*), НЕ в JWT — токен продолжает содержать
role='admin' для всех SystemUser, чтобы не ломать `_check_admin_or_system`
и совместимость. Точечные проверки в _visible_deals_query/_can_edit_deal/etc
используют эти хелперы.
"""

from flask import g

from models.systemuser import SystemUser


def _cache_key(user_id: int) -> str:
    return f'_su_perm_{user_id}'


def get_perm(user_id) -> dict:
    """
    Возвращает флаги пользователя в виде dict — с кэшем внутри одного
    request'а. Читает БД максимум один раз.

    {
        'is_owner': bool,
        'can_see_all_deals': bool,
        'can_see_all_tasks': bool,
        'can_manage_pipelines': bool,
    }

    Для user_id=None или отсутствующего юзера — все False.
    """
    default = {
        'is_owner': False,
        'can_see_all_deals': False,
        'can_see_all_tasks': False,
        'can_manage_pipelines': False,
        'can_manage_projects': False,
    }
    if not user_id:
        return default
    key = _cache_key(user_id)
    if hasattr(g, key):
        return getattr(g, key)
    try:
        u = SystemUser.query.get(user_id)
    except Exception:
        u = None
    if not u:
        setattr(g, key, default)
        return default
    perm = {
        'is_owner': bool(u.is_owner),
        'can_see_all_deals': bool(u.can_see_all_deals),
        'can_see_all_tasks': bool(u.can_see_all_tasks),
        'can_manage_pipelines': bool(u.can_manage_pipelines),
        'can_manage_projects': bool(u.can_manage_projects),
    }
    setattr(g, key, perm)
    return perm


def is_owner(user_id) -> bool:
    return get_perm(user_id)['is_owner']


def can_see_all_deals(user_id) -> bool:
    p = get_perm(user_id)
    return p['is_owner'] or p['can_see_all_deals']


def can_see_all_tasks(user_id) -> bool:
    p = get_perm(user_id)
    return p['is_owner'] or p['can_see_all_tasks']


def can_manage_pipelines(user_id) -> bool:
    p = get_perm(user_id)
    return p['is_owner'] or p['can_manage_pipelines']


def can_manage_projects(user_id) -> bool:
    p = get_perm(user_id)
    return p['is_owner'] or p['can_manage_projects']
