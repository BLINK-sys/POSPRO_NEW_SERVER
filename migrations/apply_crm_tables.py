"""
Разовая миграция для CRM-модуля: создаёт 18 таблиц (Сделки/Задачи/Чат
+ сквозные `entity_attachment` и `crm_ingest_source`) и заливает seed:

  1. Дефолтная воронка «Основная» с 5 стадиями (Новая · В работе ·
     Ожидает КП · Выиграна · Проиграна) — чтобы Kanban на старте
     Этапа 3 был не пустой.
  2. Общий чат-комната (`chat_room.kind='general'`, name='Общий') +
     membership для всех `system_users`.
  3. Два internal-источника `crm_ingest_source`: `order` и
     `price_request` → воронка «Основная», стадия «Новая», стратегия
     `unassigned`. После раскатки сделки сами начнут появляться из
     обработчиков заказов и уточнений цены.

Идемпотентно: `CREATE TABLE IF NOT EXISTS` в SQL, а сидовые вставки
защищены `ON CONFLICT`/проверками существования. Скрипт можно
перезапускать без последствий.

Запуск (Render Shell или локально):
    cd pospro_new_server
    python -u -m migrations.apply_crm_tables

Полная картина — `PosPro/Магазин PosPro/Доменные области/31 CRM и
двумодовая навигация (планирование).md`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from extensions import db
from sqlalchemy import text


SQL_PATH = os.path.join(os.path.dirname(__file__), 'create_crm_tables.sql')

# Полный список созданных таблиц — для verify-отчёта в конце.
CRM_TABLES = [
    'deal_pipeline', 'deal_stage', 'deal',
    'deal_member', 'deal_kp', 'deal_order', 'deal_activity',
    'task', 'task_member', 'task_checklist', 'task_activity',
    'chat_room', 'chat_member', 'chat_message', 'chat_reaction', 'chat_attachment',
    'entity_attachment', 'crm_ingest_source',
]

DEFAULT_PIPELINE_NAME = 'Основная'
DEFAULT_STAGES = [
    # (name, color, type, order)
    ('Новая',       '#94a3b8', 'normal', 0),
    ('В работе',    '#3b82f6', 'normal', 1),
    ('Ожидает КП',  '#f59e0b', 'normal', 2),
    ('Выиграна',    '#22c55e', 'won',    3),
    ('Проиграна',   '#ef4444', 'lost',   4),
]

GENERAL_CHAT_NAME = 'Общий'

# Internal-источники ingest'а сидируются с воронкой «Основная», стадией
# «Новая», стратегия — `unassigned` (сделка попадает в очередь «Свободные»,
# распределение делает админ вручную из UI).
INTERNAL_INGEST_SEEDS = [
    {
        'source_key': 'order',
        'name': 'Заказы с сайта',
        'title_template': 'Заказ #{source_ref_id}',
        'notes_template': None,
    },
    {
        'source_key': 'price_request',
        'name': 'Уточнения цены с сайта',
        'title_template': 'Уточнение цены — {product_name}',
        'notes_template': None,
    },
]


def _apply_sql():
    """Читает `create_crm_tables.sql` и выполняет по одному statement."""
    with open(SQL_PATH, encoding='utf-8') as f:
        sql = f.read()

    # Комментарии в SQL начинаются с '--'. Разбиение по ';' допустимо
    # только потому что тут нет функций / DO-блоков / триггеров с
    # внутренними точкой с запятой.
    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

    print(f'Statements to execute: {len(statements)}', flush=True)
    for i, stmt in enumerate(statements, 1):
        first_line = stmt.splitlines()[0][:80]
        print(f'  [{i:>2}/{len(statements)}] {first_line}...', flush=True)
        db.session.execute(text(stmt))

    db.session.commit()


# Список таблиц, где есть колонки created_at / updated_at — используется
# для post-DDL ALTER'а. Проблема, которую он решает: `app.py:216`
# `db.create_all()` при рестарте после раскатки коммита создаёт таблицы
# без DB-level DEFAULT'ов (модели используют Python-side `default=`,
# без `server_default=`). После этого `CREATE TABLE IF NOT EXISTS` в моей
# миграции пропускается, и raw-SQL INSERT'ы падают с NOT NULL violation
# на created_at. ALTER доставляет дефолты post-fact — идемпотентно, PG
# просто перезапишет existing DEFAULT если он и так есть.
_TABLES_WITH_TIMESTAMPS = [
    ('deal_pipeline',      ('created_at', 'updated_at')),
    ('deal_stage',         ('created_at', 'updated_at')),
    ('deal',               ('created_at', 'updated_at')),
    ('deal_member',        ('added_at',)),
    ('deal_kp',            ('attached_at',)),
    ('deal_order',         ('attached_at',)),
    ('deal_activity',      ('created_at',)),
    ('task',               ('created_at', 'updated_at')),
    ('task_member',        ('added_at',)),
    ('task_checklist',     ('created_at',)),
    ('task_activity',      ('created_at',)),
    ('chat_room',          ('created_at', 'updated_at')),
    ('chat_member',        ('joined_at',)),
    ('chat_message',       ('created_at',)),
    ('chat_reaction',      ('created_at',)),
    ('chat_attachment',    ('created_at',)),
    ('entity_attachment',  ('uploaded_at',)),
    ('crm_ingest_source',  ('created_at', 'updated_at')),
]


def _ensure_timestamp_defaults():
    """
    Добавляет `DEFAULT CURRENT_TIMESTAMP` на все timestamp-колонки CRM-
    таблиц. Нужно потому что `db.create_all()` в app.py создал таблицы
    без DEFAULT'ов, а моя SQL-миграция с ними была пропущена через
    IF NOT EXISTS.
    """
    print('', flush=True)
    print('=== Ensure timestamp DEFAULTs ===', flush=True)
    for tbl, cols in _TABLES_WITH_TIMESTAMPS:
        for col in cols:
            db.session.execute(text(
                f'ALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT CURRENT_TIMESTAMP'
            ))
        print(f'  {tbl}: {", ".join(cols)} → DEFAULT CURRENT_TIMESTAMP', flush=True)
    db.session.commit()


def _seed_default_pipeline():
    """
    Создаёт «Основную» воронку и 5 стадий, если ещё нет.
    Возвращает `(pipeline_id, stages_by_name)`.

    Все timestamp'ы передаются явно через NOW() — на случай если
    таблицы были созданы `db.create_all()`'ом без DB-level DEFAULT'ов
    (см. `_ensure_timestamp_defaults`).
    """
    pipeline_id = db.session.execute(
        text('SELECT id FROM deal_pipeline WHERE name = :n LIMIT 1'),
        {'n': DEFAULT_PIPELINE_NAME},
    ).scalar()

    if pipeline_id is None:
        pipeline_id = db.session.execute(
            text(
                'INSERT INTO deal_pipeline (name, "order", active, created_at, updated_at) '
                "VALUES (:n, 0, true, NOW(), NOW()) RETURNING id"
            ),
            {'n': DEFAULT_PIPELINE_NAME},
        ).scalar()
        print(f'  seed: pipeline «{DEFAULT_PIPELINE_NAME}» created (id={pipeline_id})', flush=True)
    else:
        print(f'  seed: pipeline «{DEFAULT_PIPELINE_NAME}» exists (id={pipeline_id})', flush=True)

    stages_by_name = {}
    for name, color, stype, order in DEFAULT_STAGES:
        stage_id = db.session.execute(
            text(
                'SELECT id FROM deal_stage '
                'WHERE pipeline_id = :p AND name = :n LIMIT 1'
            ),
            {'p': pipeline_id, 'n': name},
        ).scalar()
        if stage_id is None:
            stage_id = db.session.execute(
                text(
                    'INSERT INTO deal_stage '
                    '(pipeline_id, name, color, "order", type, created_at, updated_at) '
                    'VALUES (:p, :n, :c, :o, :t, NOW(), NOW()) RETURNING id'
                ),
                {'p': pipeline_id, 'n': name, 'c': color, 'o': order, 't': stype},
            ).scalar()
            print(f'    stage «{name}» created (id={stage_id})', flush=True)
        stages_by_name[name] = stage_id

    db.session.commit()
    return pipeline_id, stages_by_name


def _seed_general_chat():
    """Создаёт общую комнату + membership для всех system_users."""
    room_id = db.session.execute(
        text("SELECT id FROM chat_room WHERE kind = 'general' LIMIT 1"),
    ).scalar()

    if room_id is None:
        room_id = db.session.execute(
            text(
                "INSERT INTO chat_room (kind, name, created_at, updated_at) "
                "VALUES ('general', :n, NOW(), NOW()) RETURNING id"
            ),
            {'n': GENERAL_CHAT_NAME},
        ).scalar()
        print(f'  seed: general chat room created (id={room_id})', flush=True)
    else:
        print(f'  seed: general chat room exists (id={room_id})', flush=True)

    # Добавляем всех system_user'ов которые ещё не в комнате.
    added = db.session.execute(
        text(
            'INSERT INTO chat_member (room_id, user_id, joined_at) '
            'SELECT :r, su.id, NOW() FROM system_users su '
            'WHERE NOT EXISTS ('
            '  SELECT 1 FROM chat_member cm '
            '  WHERE cm.room_id = :r AND cm.user_id = su.id'
            ') '
            'RETURNING id'
        ),
        {'r': room_id},
    ).rowcount
    if added:
        print(f'    added {added} system_users to general chat', flush=True)
    db.session.commit()


def _seed_internal_ingest_sources(pipeline_id, stages_by_name):
    """Заводит `order` и `price_request` internal-источники."""
    stage_id = stages_by_name['Новая']

    for seed in INTERNAL_INGEST_SEEDS:
        existing = db.session.execute(
            text(
                'SELECT id FROM crm_ingest_source '
                'WHERE kind = :k AND source_key = :s LIMIT 1'
            ),
            {'k': 'internal', 's': seed['source_key']},
        ).scalar()

        if existing is None:
            new_id = db.session.execute(
                text(
                    'INSERT INTO crm_ingest_source '
                    '(kind, source_key, name, pipeline_id, stage_id, '
                    ' title_template, notes_template, priority, '
                    ' assignment_strategy, client_resolution, dedupe_by_ref, active, '
                    ' created_at, updated_at) '
                    "VALUES ('internal', :sk, :n, :p, :st, :tt, :nt, 'normal', "
                    "        'unassigned', 'find_by_email', true, true, "
                    '        NOW(), NOW()) '
                    'RETURNING id'
                ),
                {
                    'sk': seed['source_key'],
                    'n': seed['name'],
                    'p': pipeline_id,
                    'st': stage_id,
                    'tt': seed['title_template'],
                    'nt': seed['notes_template'],
                },
            ).scalar()
            print(f'  seed: ingest source «{seed["name"]}» created (id={new_id})', flush=True)
        else:
            print(f'  seed: ingest source «{seed["name"]}» exists (id={existing})', flush=True)

    db.session.commit()


def _verify():
    """Печатает количество строк в каждой из 18 CRM-таблиц."""
    print('', flush=True)
    print('=== CRM tables ===', flush=True)
    for tbl in CRM_TABLES:
        count = db.session.execute(text(f'SELECT COUNT(*) FROM {tbl}')).scalar()
        print(f'  {tbl:<24} {count:>6} rows', flush=True)


def apply():
    _apply_sql()
    _ensure_timestamp_defaults()
    print('', flush=True)
    print('=== Seed ===', flush=True)
    pipeline_id, stages_by_name = _seed_default_pipeline()
    _seed_general_chat()
    _seed_internal_ingest_sources(pipeline_id, stages_by_name)
    _verify()
    print('', flush=True)
    print('OK', flush=True)


if __name__ == '__main__':
    with app.app_context():
        apply()
