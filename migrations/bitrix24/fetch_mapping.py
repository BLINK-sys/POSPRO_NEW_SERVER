"""
Шаг 1 миграции из Б24: собрать меты и сгенерировать черновой маппинг.

Что делает:
  1. Выгружает активных юзеров Б24 (user.get) + все воронки/стадии
     (crm.dealcategory.list / stage.list, включая категорию 0 — базовую).
  2. Берёт из нашей БД: активных system_users, воронки + стадии.
  3. Строит авто-маппинг:
       - пользователи — по совпадению email (case-insensitive, trim)
       - воронки — по совпадению названия (lower, trim)
       - стадии — внутри каждой пары воронок по совпадению названия
  4. Печатает JSON в stdout и сохраняет в
     `/opt/render/project/src/disk/b24_mapping.json`
     (или в `/tmp/b24_mapping.json` если /disk отсутствует).

После выполнения:
  - юзер смотрит лог Job'а в Render → копирует JSON → редактирует вручную,
    где авто-маппинг пустой → коммитит в репо как
    `migrations/bitrix24/b24_mapping.json`.
  - следующий Job (migrate_*) этот файл подхватит.

Запуск: python -u -m migrations.bitrix24.fetch_mapping
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import app
from extensions import db
from sqlalchemy import text as sql_text

from migrations.bitrix24._b24 import call as b24_call


OUT_PATHS = [
    '/disk/b24_migration/b24_mapping.json',
    '/tmp/b24_mapping.json',
]


def _norm_email(e: str | None) -> str:
    return (e or '').strip().lower()


def _norm_name(s: str | None) -> str:
    return ''.join((s or '').strip().lower().split())


def fetch_b24_users() -> list[dict]:
    print('→ fetching Б24 users…', flush=True)
    out = b24_call('user.get', {'ACTIVE': 'true'})
    users = out.get('result') or []
    print(f'  got {len(users)} active users', flush=True)
    return users


def fetch_b24_categories() -> list[dict]:
    print('→ fetching Б24 pipelines…', flush=True)
    out = b24_call('crm.dealcategory.list')
    cats = out.get('result') or []
    # Категория 0 (базовая) не возвращается этим методом — добавим вручную.
    cats_with_zero = [{'ID': 0, 'NAME': 'Общая (базовая)'}] + list(cats)
    print(f'  got {len(cats_with_zero)} pipelines (including base)', flush=True)
    return cats_with_zero


def fetch_b24_stages(category_id: int) -> list[dict]:
    out = b24_call('crm.dealcategory.stage.list', {'id': category_id})
    return out.get('result') or []


def fetch_pospro_users() -> list[dict]:
    # В модели нет флага активности — тащим всех. Для миграции важно
    # просто иметь список для подбора по email.
    from models.systemuser import SystemUser
    out = []
    for u in SystemUser.query.order_by(SystemUser.full_name).all():
        out.append({'id': u.id, 'name': u.full_name, 'email': u.email})
    return out


def fetch_pospro_email_aliases() -> dict[str, int]:
    """
    Email-алиасы для system_users: `alt_email → user_id`. Нужны чтобы
    смерженные дубли (например ant@pospro.kz → id основного юзера)
    не создавались повторно при следующем B24-импорте.

    Таблица создаётся миграцией apply_system_user_email_alias.py — если
    её нет, тихо возвращаем пустую мапу.
    """
    from extensions import db
    from sqlalchemy import text
    try:
        rows = db.session.execute(text(
            "SELECT email, user_id FROM system_user_email_alias"
        )).fetchall()
    except Exception:
        return {}
    return {_norm_email(r.email): int(r.user_id) for r in rows}


def fetch_pospro_pipelines() -> list[dict]:
    from models.deal_pipeline import DealPipeline
    out = []
    for p in DealPipeline.query.order_by(DealPipeline.order).all():
        out.append({
            'id': p.id,
            'name': p.name,
            'active': bool(p.active),
            'stages': [
                {'id': s.id, 'name': s.name, 'type': s.type, 'order': s.order}
                for s in sorted(p.stages, key=lambda x: x.order)
            ],
        })
    return out


def build_user_mapping(
    b24: list[dict],
    pospro: list[dict],
    aliases: dict[str, int] | None = None,
) -> dict:
    """
    Авто-маппинг по email. Сначала точное совпадение по основному email,
    затем — через email-алиасы (`system_user_email_alias`): позволяет
    замерженным дублям b24-юзера автоматически привязываться к основному
    system_user, не создавая запись заново.

    unmatched = список Б24-юзеров без совпадения — их пользователь должен
    ручно привязать (или решить что они не нужны).
    """
    by_email = {_norm_email(u['email']): u for u in pospro if u.get('email')}
    by_id = {u['id']: u for u in pospro}
    aliases = aliases or {}

    def _resolve(email: str):
        """Возвращает pospro-юзера или None. Сначала основной email, потом alias."""
        if not email:
            return None, None
        hit = by_email.get(email)
        if hit:
            return hit, None
        alias_uid = aliases.get(email)
        if alias_uid and alias_uid in by_id:
            return by_id[alias_uid], 'alias'
        return None, None

    mapping = {}
    unmatched = []
    for u in b24:
        email = _norm_email(u.get('EMAIL'))
        last = (u.get('LAST_NAME') or '').strip()
        first = (u.get('NAME') or '').strip()
        full = f'{last} {first}'.strip() or email or f'ID {u["ID"]}'
        hit, via = _resolve(email)
        entry = {
            'b24_id': int(u['ID']),
            'b24_name': full,
            'b24_email': u.get('EMAIL'),
            'pospro_id': hit['id'] if hit else None,
            'pospro_name': hit['name'] if hit else None,
            'match_via': via,  # 'alias' если через alias, иначе None
        }
        mapping[str(u['ID'])] = entry
        if not hit:
            unmatched.append(entry)
    return {
        'map': mapping,
        'unmatched_count': len(unmatched),
        'unmatched_sample': unmatched[:20],
    }


def build_pipeline_mapping(b24_cats: list[dict], pospro: list[dict]) -> dict:
    by_name = {_norm_name(p['name']): p for p in pospro}
    out = {}
    for c in b24_cats:
        b24_name = (c.get('NAME') or '').strip()
        hit = by_name.get(_norm_name(b24_name))
        out[str(c['ID'])] = {
            'b24_id': int(c['ID']),
            'b24_name': b24_name,
            'pospro_id': hit['id'] if hit else None,
            'pospro_name': hit['name'] if hit else None,
        }
    return out


def build_stage_mapping(
    b24_stages_by_cat: dict[int, list[dict]],
    b24_cats: list[dict],
    pipeline_map: dict,
    pospro_pipelines: list[dict],
) -> dict:
    """
    Для каждой B24-воронки с замапленной PosPro-воронкой — строим
    маппинг stages внутри неё.
    """
    pospro_by_id = {p['id']: p for p in pospro_pipelines}
    out = {}
    for c in b24_cats:
        cid = int(c['ID'])
        pm = pipeline_map.get(str(cid), {})
        pospro_pid = pm.get('pospro_id')
        pospro_stages_by_name = {}
        if pospro_pid and pospro_pid in pospro_by_id:
            pospro_stages_by_name = {
                _norm_name(s['name']): s for s in pospro_by_id[pospro_pid]['stages']
            }
        for s in b24_stages_by_cat.get(cid, []):
            b24_stage_id = s.get('STATUS_ID')
            b24_name = (s.get('NAME') or '').strip()
            hit = pospro_stages_by_name.get(_norm_name(b24_name))
            out[b24_stage_id] = {
                'b24_stage_id': b24_stage_id,
                'b24_name': b24_name,
                'b24_category_id': cid,
                'pospro_pipeline_id': pospro_pid,
                'pospro_stage_id': hit['id'] if hit else None,
                'pospro_stage_name': hit['name'] if hit else None,
            }
    return out


def main():
    print('=== B24 → PosPro mapping builder ===', flush=True)

    b24_users = fetch_b24_users()
    b24_cats = fetch_b24_categories()

    b24_stages_by_cat: dict[int, list[dict]] = {}
    for c in b24_cats:
        cid = int(c['ID'])
        print(f'→ stages for category {cid} ({c.get("NAME")!r})…', flush=True)
        b24_stages_by_cat[cid] = fetch_b24_stages(cid)
        print(f'  got {len(b24_stages_by_cat[cid])} stages', flush=True)

    with app.app_context():
        pospro_users = fetch_pospro_users()
        pospro_pipelines = fetch_pospro_pipelines()
        pospro_aliases = fetch_pospro_email_aliases()

    print(
        f'\nPosPro state:\n'
        f'  users: {len(pospro_users)}\n'
        f'  pipelines: {len(pospro_pipelines)}\n'
        f'  stages total: {sum(len(p["stages"]) for p in pospro_pipelines)}\n',
        flush=True,
    )

    user_map = build_user_mapping(b24_users, pospro_users, pospro_aliases)
    pipeline_map = build_pipeline_mapping(b24_cats, pospro_pipelines)
    stage_map = build_stage_mapping(
        b24_stages_by_cat, b24_cats, pipeline_map, pospro_pipelines,
    )

    report = {
        'users': user_map,
        'pipelines': pipeline_map,
        'stages': stage_map,
        'generated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
    }

    # Статистика по маппингу
    users_total = len(user_map['map'])
    users_matched = sum(1 for v in user_map['map'].values() if v['pospro_id'])
    pipes_total = len(pipeline_map)
    pipes_matched = sum(1 for v in pipeline_map.values() if v['pospro_id'])
    stages_total = len(stage_map)
    stages_matched = sum(1 for v in stage_map.values() if v['pospro_stage_id'])

    print('\n=== MAPPING SUMMARY ===', flush=True)
    print(f'  Users:     {users_matched}/{users_total} matched by email', flush=True)
    print(f'  Pipelines: {pipes_matched}/{pipes_total} matched by name', flush=True)
    print(f'  Stages:    {stages_matched}/{stages_total} matched (within matched pipelines)', flush=True)

    print('\n=== UNMATCHED USERS (first 20) ===', flush=True)
    for e in user_map['unmatched_sample']:
        print(f'  B24 #{e["b24_id"]}  {e["b24_name"]!r}  <{e["b24_email"]}>', flush=True)

    print('\n=== UNMATCHED PIPELINES ===', flush=True)
    for pid, p in pipeline_map.items():
        if not p['pospro_id']:
            print(f'  B24 cat {pid}  {p["b24_name"]!r}', flush=True)

    print('\n=== UNMATCHED STAGES ===', flush=True)
    cnt = 0
    for sid, s in stage_map.items():
        if s['pospro_pipeline_id'] and not s['pospro_stage_id']:
            print(
                f'  B24 cat {s["b24_category_id"]}  stage {sid}  {s["b24_name"]!r}',
                flush=True,
            )
            cnt += 1
            if cnt >= 50:
                print('  … (truncated at 50)', flush=True)
                break

    # Запись в файл
    saved = None
    for path in OUT_PATHS:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            saved = path
            break
        except Exception as e:
            print(f'  (could not save to {path}: {e})', flush=True)
    if saved:
        size_kb = os.path.getsize(saved) / 1024
        print(f'\n✅ Mapping saved to: {saved} ({size_kb:.1f} KB)', flush=True)
        print(
            'Retrieve via: GET /api/admin/b24-migration/mapping (owner-only)',
            flush=True,
        )


if __name__ == '__main__':
    main()
