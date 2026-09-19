"""
Админ-CRUD для правил ingest'а (`crm_ingest_source`) и тестового вызова.

Endpoints:
  GET    /api/admin/crm-sources                  список правил
  POST   /api/admin/crm-sources                  создать (webhook или internal)
  GET    /api/admin/crm-sources/<id>             детали (с токеном для webhook)
  PUT    /api/admin/crm-sources/<id>             обновить
  DELETE /api/admin/crm-sources/<id>             удалить
  POST   /api/admin/crm-sources/<id>/rotate-token   перегенерить токен
  POST   /api/admin/crm-sources/<id>/test           тестовый вызов (dry-run)

Access: только `role='admin'` — включает выбор в кого что пойдёт, это
организационная настройка.

Токен генерируется как `wh_<32hex>` через `secrets.token_hex(16)` —
криптографически стойкая случайность.

`test`-endpoint пробует создать сделку по mock-payload'у в транзакции
и откатывает её — админ видит какая сделка получится, ничего в БД не
попадает.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models.crm_ingest_source import (
    CrmIngestSource,
    CRM_INGEST_KINDS,
    CRM_INGEST_ASSIGNMENT_STRATEGIES,
    CRM_INGEST_CLIENT_RESOLUTIONS,
    CRM_INGEST_PRIORITIES,
)
from models.deal_pipeline import DealPipeline, DealStage
from models.systemuser import SystemUser
from services.crm_ingest import _apply  # используется в /test


crm_sources_bp = Blueprint('crm_sources', __name__)


# ============================================================================
# Auth
# ============================================================================

def _check_admin_only():
    role = (get_jwt() or {}).get('role')
    if role != 'admin':
        return jsonify({'error': 'Настройка ingest-источников доступна только администратору'}), 403
    return None


def _current_user_id() -> int | None:
    try:
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        return None


# ============================================================================
# Token generation
# ============================================================================

def _generate_token() -> str:
    """
    `wh_<32hex>` — 32 hex-символа (128 бит энтропии) с префиксом.
    Префикс делает токен визуально распознаваемым в логах/URL.
    """
    return f'wh_{secrets.token_hex(16)}'


# ============================================================================
# Валидация
# ============================================================================

def _parse_payload(data: dict, *, partial: bool = False, current: CrmIngestSource | None = None):
    """Возвращает `(ok, error, fields)`. Часть валидаций делается в _validate_ready."""
    fields = {}

    if not partial:
        kind = data.get('kind')
        if kind not in CRM_INGEST_KINDS:
            return False, f'kind: {", ".join(CRM_INGEST_KINDS)}', {}
        fields['kind'] = kind

    for k in ('name', 'title_template'):
        v = data.get(k)
        if v is not None:
            v = str(v).strip()
        if not partial and not v:
            return False, f'{k} обязателен', {}
        if v is not None:
            fields[k] = v

    if 'notes_template' in data:
        v = data.get('notes_template')
        fields['notes_template'] = (str(v).strip() or None) if v is not None else None

    kind_effective = fields.get('kind') or (current and current.kind)
    if kind_effective == 'internal':
        # source_key обязателен для internal при create; для update может
        # остаться прежним.
        sk = data.get('source_key')
        if sk is not None:
            sk = str(sk).strip() or None
        if not partial and not sk:
            return False, 'source_key обязателен для kind=internal', {}
        if sk is not None:
            fields['source_key'] = sk

    for k in ('pipeline_id', 'stage_id'):
        if k in data:
            try:
                fields[k] = int(data[k])
            except (TypeError, ValueError):
                return False, f'{k} должен быть числом', {}
        elif not partial:
            return False, f'{k} обязателен', {}

    if 'priority' in data:
        p = data.get('priority')
        if p and p not in CRM_INGEST_PRIORITIES:
            return False, f'priority: {", ".join(CRM_INGEST_PRIORITIES)}', {}
        if p:
            fields['priority'] = p

    if 'assignment_strategy' in data:
        s = data.get('assignment_strategy')
        if s and s not in CRM_INGEST_ASSIGNMENT_STRATEGIES:
            return False, f'assignment_strategy: {", ".join(CRM_INGEST_ASSIGNMENT_STRATEGIES)}', {}
        if s:
            fields['assignment_strategy'] = s

    if 'client_resolution' in data:
        cr = data.get('client_resolution')
        if cr and cr not in CRM_INGEST_CLIENT_RESOLUTIONS:
            return False, f'client_resolution: {", ".join(CRM_INGEST_CLIENT_RESOLUTIONS)}', {}
        if cr:
            fields['client_resolution'] = cr

    if 'pool_user_ids' in data:
        pool = data.get('pool_user_ids') or []
        if not isinstance(pool, list):
            return False, 'pool_user_ids должен быть массивом', {}
        try:
            pool = [int(x) for x in pool]
        except (TypeError, ValueError):
            return False, 'pool_user_ids: элементы должны быть числами', {}
        fields['pool_user_ids'] = pool

    if 'fixed_user_id' in data:
        v = data.get('fixed_user_id')
        if v is None or v == '':
            fields['fixed_user_id'] = None
        else:
            try:
                fields['fixed_user_id'] = int(v)
            except (TypeError, ValueError):
                return False, 'fixed_user_id должен быть числом', {}

    if 'dedupe_by_ref' in data:
        fields['dedupe_by_ref'] = bool(data.get('dedupe_by_ref'))
    if 'active' in data:
        fields['active'] = bool(data.get('active'))

    return True, None, fields


def _validate_refs(fields: dict, current: CrmIngestSource | None):
    """Проверяет что pipeline_id/stage_id/fixed_user_id/pool юзеры существуют и валидны."""
    pipeline_id = fields.get('pipeline_id') if 'pipeline_id' in fields else (current.pipeline_id if current else None)
    stage_id = fields.get('stage_id') if 'stage_id' in fields else (current.stage_id if current else None)
    if pipeline_id is not None and not DealPipeline.query.get(pipeline_id):
        return False, 'Воронка не найдена'
    if stage_id is not None:
        stage = DealStage.query.get(stage_id)
        if not stage:
            return False, 'Стадия не найдена'
        if stage.pipeline_id != pipeline_id:
            return False, 'Стадия не принадлежит указанной воронке'

    strategy = fields.get('assignment_strategy') if 'assignment_strategy' in fields else (current.assignment_strategy if current else 'unassigned')
    pool = fields.get('pool_user_ids') if 'pool_user_ids' in fields else (current.pool_user_ids if current else [])
    fixed = fields.get('fixed_user_id') if 'fixed_user_id' in fields else (current.fixed_user_id if current else None)

    if strategy == 'fixed' and not fixed:
        return False, 'Для strategy=fixed нужен fixed_user_id'
    if strategy in ('round_robin', 'least_busy') and not pool:
        return False, f'Для strategy={strategy} нужен pool_user_ids (список менеджеров)'
    for uid in (pool or []):
        if not SystemUser.query.get(uid):
            return False, f'Пользователь id={uid} не найден'
    if fixed and not SystemUser.query.get(fixed):
        return False, f'Пользователь id={fixed} не найден'

    return True, None


# ============================================================================
# CRUD
# ============================================================================

@crm_sources_bp.route('/admin/crm-sources', methods=['GET'])
@jwt_required()
def list_sources():
    """
    Список правил. `?kind=internal|webhook` — фильтр.
    Токен НЕ раскрываем в списке — только в details / после создания.
    """
    err = _check_admin_only()
    if err:
        return err

    q = CrmIngestSource.query
    kind = request.args.get('kind')
    if kind in CRM_INGEST_KINDS:
        q = q.filter_by(kind=kind)
    items = q.order_by(CrmIngestSource.created_at.desc()).all()
    return jsonify({
        'success': True,
        'sources': [s.to_dict(expose_token=False) for s in items],
    }), 200


@crm_sources_bp.route('/admin/crm-sources/<int:sid>', methods=['GET'])
@jwt_required()
def get_source(sid):
    """
    Детали. Токен раскрывается в поле `token` — чтобы админ мог
    скопировать URL webhook'а.
    """
    err = _check_admin_only()
    if err:
        return err
    s = CrmIngestSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404
    return jsonify({'success': True, 'source': s.to_dict(expose_token=True)}), 200


@crm_sources_bp.route('/admin/crm-sources', methods=['POST'])
@jwt_required()
def create_source():
    err = _check_admin_only()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400
    ok, msg = _validate_refs(fields, None)
    if not ok:
        return jsonify({'error': msg}), 400

    kind = fields['kind']
    token = _generate_token() if kind == 'webhook' else None
    if kind == 'internal':
        # Проверим что source_key уникален
        existing = CrmIngestSource.query.filter_by(
            kind='internal', source_key=fields.get('source_key'),
        ).first()
        if existing:
            return jsonify({
                'error': f'Внутренний источник с source_key={fields.get("source_key")} уже существует'
            }), 409

    s = CrmIngestSource(
        kind=kind,
        source_key=fields.get('source_key') if kind == 'internal' else None,
        token=token,
        name=fields['name'],
        pipeline_id=fields['pipeline_id'],
        stage_id=fields['stage_id'],
        title_template=fields['title_template'],
        notes_template=fields.get('notes_template'),
        priority=fields.get('priority', 'normal'),
        assignment_strategy=fields.get('assignment_strategy', 'unassigned'),
        pool_user_ids=fields.get('pool_user_ids', []),
        fixed_user_id=fields.get('fixed_user_id'),
        client_resolution=fields.get('client_resolution', 'none'),
        dedupe_by_ref=fields.get('dedupe_by_ref', True),
        active=fields.get('active', True),
        created_by=_current_user_id(),
    )
    db.session.add(s)
    db.session.commit()
    # После создания токен НЕ секрет — админ его увидит один раз в модалке.
    return jsonify({'success': True, 'source': s.to_dict(expose_token=True)}), 201


@crm_sources_bp.route('/admin/crm-sources/<int:sid>', methods=['PUT'])
@jwt_required()
def update_source(sid):
    err = _check_admin_only()
    if err:
        return err

    s = CrmIngestSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data, partial=True, current=s)
    if not ok:
        return jsonify({'error': msg}), 400
    ok, msg = _validate_refs(fields, s)
    if not ok:
        return jsonify({'error': msg}), 400

    # kind менять нельзя — это меняет семантику записи (проверка CHECK
    # constraint и вся ветка). Если нужен другой kind — создать заново.
    if 'kind' in fields and fields['kind'] != s.kind:
        return jsonify({'error': 'Смена kind не поддерживается, создайте новую запись'}), 400

    for k, v in fields.items():
        if k == 'kind':
            continue
        setattr(s, k, v)
    s.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'source': s.to_dict(expose_token=True)}), 200


@crm_sources_bp.route('/admin/crm-sources/<int:sid>', methods=['DELETE'])
@jwt_required()
def delete_source(sid):
    err = _check_admin_only()
    if err:
        return err

    s = CrmIngestSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404

    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True}), 200


@crm_sources_bp.route('/admin/crm-sources/<int:sid>/rotate-token', methods=['POST'])
@jwt_required()
def rotate_token(sid):
    """
    Перегенерирует токен webhook'а. Старый URL сразу перестаёт работать —
    внешний сервис должен быть переконфигурирован на новый URL.
    """
    err = _check_admin_only()
    if err:
        return err

    s = CrmIngestSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404
    if s.kind != 'webhook':
        return jsonify({'error': 'Ротация токена доступна только для webhook-источников'}), 400

    s.token = _generate_token()
    s.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'source': s.to_dict(expose_token=True)}), 200


# ============================================================================
# Test (dry-run)
# ============================================================================

@crm_sources_bp.route('/admin/crm-sources/<int:sid>/test', methods=['POST'])
@jwt_required()
def test_source(sid):
    """
    Тестовый вызов ingest-правила. Принимает mock-payload в теле,
    прогоняет через _apply, но всё делается в транзакции и откатывается —
    в БД ничего не остаётся. Возвращает preview созданной сделки.

    Так админ может проверить настройку правила (шаблоны, назначение
    ответственного, резолвинг клиента) не создавая мусорных сделок.
    """
    err = _check_admin_only()
    if err:
        return err

    s = CrmIngestSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'error': 'Payload должен быть объектом'}), 400

    # savepoint позволит откатить всё что натворил _apply, оставив
    # исходную транзакцию нетронутой.
    try:
        savepoint = db.session.begin_nested()
        result = _apply(s, payload)
        preview = None
        if result.ok and result.deal_id:
            from models.deal import Deal
            deal = Deal.query.get(result.deal_id)
            if deal:
                preview = deal.to_dict()
        # Откатываем всё (создание сделки, activity, изменения rule.stats).
        savepoint.rollback()
        # Внешняя транзакция всё ещё активна — коммитим её пустой, чтобы
        # SQLAlchemy сессия не подвисла.
        db.session.rollback()
        return jsonify({
            'success': True,
            'result': {
                'ok': result.ok,
                'deal_id': result.deal_id,
                'responsible_id': result.responsible_id,
                'dedupe': result.dedupe,
                'error': result.error,
            },
            'preview_deal': preview,
            'note': 'Тестовый вызов, ничего не сохранено в БД',
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Тестовый вызов упал: {e}'}), 500
