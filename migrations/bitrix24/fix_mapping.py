"""
Шаг «подготовка маппинга» миграции из Б24. Standalone: сам тянет мету
из Б24 + БД (не зависит от файла с диска, т.к. /disk у Render Jobs
не persistent между запусками).

Действия (все идемпотентны):
  1. Создаёт в PosPro недостающих `system_users` по email из Б24.
     Пароль — временный `b24-import-<b24_id>` (owner потом сбросит).
     Флаги — минимальные: обычный менеджер.
  2. Авто-матчинг воронок по name (ё→е, lower, strip) + явные
     override'ы (cat 0 'Общая (базовая)' → 'Розница').
  3. Для каждой Б24-стадии в замапленной воронке создаёт недостающую
     PosPro-стадию с именем 1:1 из Б24, type:
       STATUS_ID оканчивается ':WON' → 'won'
       STATUS_ID оканчивается ':LOSE' / ':APOLOGY' → 'lost'
       остальное → 'normal'
  4. Сохраняет финальный маппинг в БД (таблица `b24_meta`, key='mapping')
     — чтобы следующие Jobs (migrate_*) его читали.

Запуск:
    python -u -m migrations.bitrix24.fix_mapping
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

# Явные override'ы когда авто-матчинг по имени ошибается.
PIPELINE_OVERRIDES_BY_B24_ID = {
    0: 'Розница',
    # cat 1 закроется через fuzzy ё/е.
}


def _norm(s: str) -> str:
    return ''.join(
        (s or '').strip().lower().replace('ё', 'е').replace('й', 'и').split()
    )


def _stage_type_from_b24_id(status_id: str) -> str:
    """
    По суффиксу STATUS_ID в Б24 определяем семантику стадии.
    Б24-стандарт: WON — успех, LOSE — провал, APOLOGY — провал (анализ).
    """
    tail = status_id.split(':')[-1].upper() if status_id else ''
    if tail == 'WON':
        return 'won'
    if tail in ('LOSE', 'APOLOGY'):
        return 'lost'
    return 'normal'


def ensure_users(b24_users_map: dict) -> dict:
    """
    Проходит по unmatched юзерам и создаёт их в PosPro.
    Возвращает обновлённый user_map с заполненными pospro_id.
    """
    created = 0
    updated_map = {}
    for key, v in b24_users_map.items():
        if v['pospro_id']:
            updated_map[key] = v
            continue
        b24_id = v['b24_id']
        name = v['b24_name'] or f'B24 user #{b24_id}'
        email = (v['b24_email'] or '').strip().lower()
        if not email:
            # Нет email — пропускаем. Такие сделки/задачи повиснут на owner'е.
            print(f'  SKIP (no email): B24 #{b24_id} {name!r}', flush=True)
            updated_map[key] = v
            continue
        # Проверяем ещё раз на случай гонки.
        existing = SystemUser.query.filter(
            db.func.lower(SystemUser.email) == email
        ).first()
        if existing:
            v['pospro_id'] = existing.id
            v['pospro_name'] = existing.full_name
            print(f'  LINK existing: B24 #{b24_id} → PosPro #{existing.id} ({email})', flush=True)
            updated_map[key] = v
            continue
        pwd = f'b24-import-{b24_id}'
        u = SystemUser(
            full_name=name,
            email=email,
            is_owner=False,
            can_see_all_deals=False,
            can_see_all_tasks=False,
        )
        u.set_password(pwd)
        db.session.add(u)
        db.session.flush()
        v['pospro_id'] = u.id
        v['pospro_name'] = u.full_name
        print(f'  CREATED: B24 #{b24_id} → PosPro #{u.id} ({email})  pwd={pwd}', flush=True)
        updated_map[key] = v
        created += 1
    print(f'→ users created: {created}', flush=True)
    return updated_map


def fuzzy_pipeline_match(b24_name: str, pospro_list: list) -> dict | None:
    """Fuzzy match по нормализованному имени."""
    n = _norm(b24_name)
    for p in pospro_list:
        if _norm(p['name']) == n:
            return p
    return None


def apply_pipeline_overrides(
    pipeline_map: dict, pospro_pipelines: list,
) -> dict:
    by_name = {p['name']: p for p in pospro_pipelines}
    changed = 0
    for key, entry in pipeline_map.items():
        b24_id = entry['b24_id']
        # 1) Явный override.
        if b24_id in PIPELINE_OVERRIDES_BY_B24_ID:
            tname = PIPELINE_OVERRIDES_BY_B24_ID[b24_id]
            hit = by_name.get(tname)
            if hit and entry['pospro_id'] != hit['id']:
                entry['pospro_id'] = hit['id']
                entry['pospro_name'] = hit['name']
                print(f'  OVERRIDE: cat {b24_id} {entry["b24_name"]!r} → {hit["name"]!r}',
                      flush=True)
                changed += 1
            continue
        # 2) Fuzzy если ещё null.
        if entry['pospro_id'] is None:
            hit = fuzzy_pipeline_match(entry['b24_name'], pospro_pipelines)
            if hit:
                entry['pospro_id'] = hit['id']
                entry['pospro_name'] = hit['name']
                print(f'  FUZZY: cat {b24_id} {entry["b24_name"]!r} → {hit["name"]!r}',
                      flush=True)
                changed += 1
    print(f'→ pipeline overrides+fuzzy applied: {changed}', flush=True)
    return pipeline_map


def ensure_stages_in_pipeline(
    pospro_pipeline_id: int,
    b24_stages_for_cat: list[dict],
    b24_stages_report: dict,
) -> int:
    """
    Проходит все Б24-стадии категории и для каждой создаёт PosPro-стадию
    в указанной воронке, если её ещё нет (матчинг по _norm(name)).
    Возвращает число созданных стадий.
    Обновляет b24_stages_report in-place.
    """
    p = DealPipeline.query.get(pospro_pipeline_id)
    if not p:
        print(f'  !! pipeline #{pospro_pipeline_id} not found, skip', flush=True)
        return 0

    existing_stages = sorted(p.stages, key=lambda s: s.order)
    by_norm_name = {_norm(s.name): s for s in existing_stages}
    next_order = (max((s.order for s in existing_stages), default=0) // 10 + 1) * 10

    created = 0
    for b24_stage in b24_stages_for_cat:
        status_id = b24_stage['STATUS_ID']
        b24_name = (b24_stage.get('NAME') or '').strip()
        if not b24_name:
            continue
        report_entry = b24_stages_report.get(status_id)
        if report_entry and report_entry.get('pospro_stage_id'):
            continue
        hit = by_norm_name.get(_norm(b24_name))
        if hit:
            if report_entry:
                report_entry['pospro_pipeline_id'] = p.id
                report_entry['pospro_stage_id'] = hit.id
                report_entry['pospro_stage_name'] = hit.name
            continue
        # Создаём новую стадию.
        stype = _stage_type_from_b24_id(status_id)
        s = DealStage(
            pipeline_id=p.id,
            name=b24_name,
            type=stype,
            order=next_order,
        )
        db.session.add(s)
        db.session.flush()
        by_norm_name[_norm(b24_name)] = s
        next_order += 10
        created += 1
        print(f'  + stage {status_id!r} → #{s.id} ({b24_name!r}, type={stype})',
              flush=True)
        if report_entry is None:
            report_entry = b24_stages_report[status_id] = {
                'b24_stage_id': status_id,
                'b24_name': b24_name,
                'b24_category_id': None,
            }
        report_entry['pospro_pipeline_id'] = p.id
        report_entry['pospro_stage_id'] = s.id
        report_entry['pospro_stage_name'] = s.name
    return created


def fetch_b24_stages_for_each_cat(b24_cats: list[dict]) -> dict[int, list[dict]]:
    from migrations.bitrix24._b24 import call as b24_call
    out = {}
    for c in b24_cats:
        cid = int(c['ID'])
        r = b24_call('crm.dealcategory.stage.list', {'id': cid})
        out[cid] = r.get('result') or []
    return out


def _save_mapping_to_db(report: dict) -> None:
    """Сохраняем финальный mapping в простейшую key-value таблицу b24_meta."""
    db.session.execute(sql_text("""
        CREATE TABLE IF NOT EXISTS b24_meta (
            key VARCHAR(64) PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    db.session.execute(
        sql_text("""
            INSERT INTO b24_meta (key, value, updated_at)
            VALUES ('mapping', CAST(:v AS JSONB), NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value, updated_at = NOW()
        """),
        {'v': json.dumps(report, ensure_ascii=False)},
    )
    db.session.commit()


def main():
    print('=== fix_mapping start ===', flush=True)

    from migrations.bitrix24.fetch_mapping import (
        fetch_b24_users, fetch_b24_categories,
        fetch_pospro_users, fetch_pospro_pipelines,
        build_user_mapping, build_pipeline_mapping, build_stage_mapping,
    )

    # 1) Тянем мету из Б24.
    print('→ fetching B24 meta…', flush=True)
    b24_users = fetch_b24_users()
    b24_cats = fetch_b24_categories()
    b24_stages_by_cat = fetch_b24_stages_for_each_cat(b24_cats)

    with app.app_context():
        # 2) Тянем нашу мету.
        pospro_users = fetch_pospro_users()
        pospro_pipelines = fetch_pospro_pipelines()

        # 3) Строим авто-маппинг (как fetch_mapping делал).
        user_map = build_user_mapping(b24_users, pospro_users)
        pipeline_map = build_pipeline_mapping(b24_cats, pospro_pipelines)
        stage_map = build_stage_mapping(
            b24_stages_by_cat, b24_cats, pipeline_map, pospro_pipelines,
        )
        report = {
            'users': user_map,
            'pipelines': pipeline_map,
            'stages': stage_map,
        }

        # 4) Создаём недостающих юзеров.
        print('\n→ ensure users…', flush=True)
        report['users']['map'] = ensure_users(report['users']['map'])

        # 5) Применяем overrides + fuzzy для воронок.
        print('\n→ apply pipeline overrides + fuzzy…', flush=True)
        # Переподтянем pospro_pipelines на случай если fuzzy-match требует
        # свежий срез (мы юзеров только что добавили, но воронки не трогали —
        # можно использовать уже загруженный список).
        report['pipelines'] = apply_pipeline_overrides(
            report['pipelines'], pospro_pipelines,
        )

        # 6) Для каждой замапленной воронки создаём недостающие стадии.
        print('\n→ ensure stages (create missing)…', flush=True)
        pipeline_map = report['pipelines']
        stage_report = report['stages']
        total_created = 0
        for c in b24_cats:
            cid = int(c['ID'])
            entry = pipeline_map.get(str(cid))
            if not entry or not entry['pospro_id']:
                print(f'  skip cat {cid} ({c.get("NAME")!r}) — no pipeline mapping',
                      flush=True)
                continue
            # Дозаполним b24_category_id в stage_report для новых записей.
            for s in b24_stages_by_cat.get(cid, []):
                sid = s['STATUS_ID']
                if sid not in stage_report:
                    stage_report[sid] = {
                        'b24_stage_id': sid,
                        'b24_name': (s.get('NAME') or '').strip(),
                        'b24_category_id': cid,
                        'pospro_pipeline_id': None,
                        'pospro_stage_id': None,
                        'pospro_stage_name': None,
                    }
                else:
                    stage_report[sid]['b24_category_id'] = cid
            n = ensure_stages_in_pipeline(
                entry['pospro_id'], b24_stages_by_cat.get(cid, []), stage_report,
            )
            total_created += n
            print(f'  cat {cid}: {n} stages created', flush=True)

        db.session.commit()
        print(f'\n→ total stages created: {total_created}', flush=True)

        # Пересчёт summary.
        users_total = len(report['users']['map'])
        users_matched = sum(1 for v in report['users']['map'].values() if v['pospro_id'])
        pipes_total = len(report['pipelines'])
        pipes_matched = sum(1 for v in report['pipelines'].values() if v['pospro_id'])
        stages_total = len(report['stages'])
        stages_matched = sum(1 for v in report['stages'].values() if v['pospro_stage_id'])

        print('\n=== FINAL SUMMARY ===', flush=True)
        print(f'  Users:     {users_matched}/{users_total}', flush=True)
        print(f'  Pipelines: {pipes_matched}/{pipes_total}', flush=True)
        print(f'  Stages:    {stages_matched}/{stages_total}', flush=True)

        # 7) Сохраняем финальный mapping в БД.
        report['generated_at'] = __import__('datetime').datetime.utcnow().isoformat() + 'Z'
        _save_mapping_to_db(report)
        print('\n✅ Final mapping saved to DB (table b24_meta, key=mapping)', flush=True)
        print('   Retrieve: GET /api/admin/b24-migration/mapping', flush=True)


if __name__ == '__main__':
    main()
