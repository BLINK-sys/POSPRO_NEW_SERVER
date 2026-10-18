"""
Косметические правки после fix_mapping:
  1. Всем юзерам, созданным fix_mapping-ом (b24-импорт), ставит пароль
     '1234'. Идентификация — по email из b24_meta['mapping'].users.
  2. Всем стадиям с дефолтным серым цветом '#94a3b8' раскрашивает:
       - type='won'  → зелёный  #22c55e
       - type='lost' → красный  #ef4444
       - type='normal' → цвет из палитры по порядку в воронке

Запуск:
    python -u -m migrations.bitrix24.apply_cosmetics
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db
from sqlalchemy import text as sql_text

from models.systemuser import SystemUser
from models.deal_pipeline import DealPipeline, DealStage


# Палитра для normal-стадий — ротация по порядку. Красный/зелёный тут
# не берём, т.к. они зарезервированы под lost/won.
NORMAL_PALETTE = [
    '#f97316',  # оранжевый
    '#f59e0b',  # янтарный
    '#facc15',  # жёлтый (brand)
    '#84cc16',  # лайм
    '#14b8a6',  # бирюза
    '#06b6d4',  # циан
    '#0ea5e9',  # голубой
    '#3b82f6',  # синий
    '#6366f1',  # индиго
    '#8b5cf6',  # фиолетовый
    '#a855f7',  # пурпурный
    '#d946ef',  # фуксия
    '#ec4899',  # розовый
    '#78716c',  # тёплый серый
    '#64748b',  # холодный серый
]

NEW_PASSWORD = '1234'


def reset_imported_users_password():
    """Пароль '1234' для юзеров, созданных fix_mapping-ом."""
    row = db.session.execute(
        sql_text("SELECT value FROM b24_meta WHERE key='mapping'")
    ).fetchone()
    if not row:
        print('!! b24_meta.mapping not found — fix_mapping не прогонялся?',
              flush=True)
        return

    mapping = row[0]
    if isinstance(mapping, str):
        mapping = json.loads(mapping)

    user_map = mapping.get('users', {}).get('map', {})
    pospro_ids: list[int] = []
    for v in user_map.values():
        pid = v.get('pospro_id')
        if pid:
            pospro_ids.append(int(pid))

    if not pospro_ids:
        print('  no imported users', flush=True)
        return

    # Из них ограничимся только теми, что были СОЗДАНЫ (не замаплены на
    # существующих). Проверим по full_name совпадению с b24_name — у
    # fix_mapping created user'ов это ФИО из Б24. Если имя отличается
    # (например existing user был по email), трогать его не будем.
    changed = 0
    for v in user_map.values():
        pid = v.get('pospro_id')
        if not pid:
            continue
        b24_name = v.get('b24_name') or ''
        u = SystemUser.query.get(int(pid))
        if not u:
            continue
        # Критерий «это наш новосозданный»: full_name совпадает с b24_name.
        # Для linkned existing user'ов имя скорее всего отличается.
        if (u.full_name or '').strip() != b24_name.strip():
            continue
        u.set_password(NEW_PASSWORD)
        changed += 1
        print(f'  pwd=1234 → #{u.id} {u.email}', flush=True)
    db.session.commit()
    print(f'→ passwords reset: {changed}', flush=True)


def recolor_default_stages():
    """
    Перекрашивает все стадии с дефолтным цветом '#94a3b8'.
    Проходим по воронкам чтобы normal-палитра ротировалась независимо
    в каждой — так колонки канбана красиво расходятся.
    """
    default = '#94a3b8'
    changed = 0
    for p in DealPipeline.query.all():
        stages = sorted(p.stages, key=lambda s: s.order)
        normal_idx = 0
        for s in stages:
            if (s.color or '').lower() != default:
                continue
            if s.type == 'won':
                s.color = '#22c55e'
            elif s.type == 'lost':
                s.color = '#ef4444'
            else:
                s.color = NORMAL_PALETTE[normal_idx % len(NORMAL_PALETTE)]
                normal_idx += 1
            changed += 1
            print(f'  {p.name!r} / {s.name!r} → {s.color}', flush=True)
    db.session.commit()
    print(f'→ stages recolored: {changed}', flush=True)


def main():
    print('=== apply_cosmetics ===', flush=True)
    with app.app_context():
        print('\n→ reset passwords for imported B24 users…', flush=True)
        reset_imported_users_password()
        print('\n→ recolor default-grey stages…', flush=True)
        recolor_default_stages()
    print('\n✅ done', flush=True)


if __name__ == '__main__':
    main()
