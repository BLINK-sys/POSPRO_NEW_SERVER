"""
Endpoints для автоматических выгрузок BIO / Equip с локального сервера.

Публичная часть (JWT admin/system) — для админки магазина:
- GET  /api/admin/integrations/                     — список карточек (для /admin/integrations)
- GET  /api/admin/integrations/<type>               — детальная (settings + текущий run + история)
- PUT  /api/admin/integrations/<type>/settings      — сохранить расписание
- POST /api/admin/integrations/<type>/trigger       — поставить в очередь ручной запуск
- GET  /api/admin/integrations/<type>/current       — polling-ручка для реалтайм-прогресса
- GET  /api/admin/integrations/<type>/runs          — история выгрузок (последние N)

Internal часть (X-Integration-Key header) — для локального воркера:
- GET  /internal/integrations/<type>/settings          — воркер читает расписание
- POST /internal/integrations/<type>/heartbeat         — воркер шлёт статус
- GET  /internal/integrations/<type>/pending-command   — воркер проверяет, есть ли команда
- POST /internal/integrations/<type>/run/<run_id>      — обновить прогресс run'а
- POST /internal/integrations/<type>/run               — создать новый run
"""

import os
import json
import time
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from flask_jwt_extended import jwt_required, get_jwt, verify_jwt_in_request
from sqlalchemy import desc

from extensions import db
from models.integration import (
    IntegrationSettings, IntegrationRun, IntegrationCommand,
    INTEGRATION_TYPES, SCHEDULE_MODES, RUN_STATUSES,
)


integrations_bp = Blueprint('integrations', __name__)


# ============ Общие хелперы ============

INTEGRATION_KEY = os.getenv('INTEGRATION_KEY', 'CHANGE_ME_IN_ENV')
# Воркер шлёт heartbeat каждые 5 сек. 20 сек = 4 пропущенных подряд —
# упал (сетевая моргалка на секунду не роняет статус). Плюс polling
# админки 5 сек → макс задержка до обновления UI ~25 сек.
HEARTBEAT_TIMEOUT_SEC = 20


def _check_admin():
    jwt_data = get_jwt()
    return jwt_data.get('role') in ('admin', 'system')


def _check_integration_key():
    key = request.headers.get('X-Integration-Key') or ''
    return key == INTEGRATION_KEY and INTEGRATION_KEY != 'CHANGE_ME_IN_ENV'


def _valid_type(t):
    return t in INTEGRATION_TYPES


def _get_or_create_settings(type_):
    s = IntegrationSettings.query.filter_by(type=type_).first()
    if s is None:
        # На всякий случай — если SQL-миграция не отработала.
        s = IntegrationSettings(
            type=type_,
            enabled=False,
            schedule_mode='weekly',
            schedule_data={'days': [], 'time': '03:00'},
        )
        db.session.add(s)
        db.session.commit()
    return s


def _is_online(settings):
    if not settings.last_heartbeat_at:
        return False
    return (datetime.utcnow() - settings.last_heartbeat_at).total_seconds() < HEARTBEAT_TIMEOUT_SEC


# ============ ADMIN endpoints ============

@integrations_bp.route('/', methods=['GET'])
@jwt_required()
def list_integrations():
    """Список карточек для главной страницы /admin/integrations."""
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403

    result = []
    for t in INTEGRATION_TYPES:
        settings = _get_or_create_settings(t)
        # Последний run для карточки (успех/ошибка/сейчас идёт)
        last_run = IntegrationRun.query.filter_by(type=t).order_by(desc(IntegrationRun.started_at)).first()
        # Активный (running) run — если есть, карточка «сейчас идёт выгрузка»
        active_run = IntegrationRun.query.filter_by(type=t, status='running').first()
        result.append({
            'type': t,
            'online': _is_online(settings),
            'settings': settings.to_dict(),
            'last_run': last_run.to_dict() if last_run else None,
            'active_run': active_run.to_dict() if active_run else None,
        })
    return jsonify({'success': True, 'data': result}), 200


@integrations_bp.route('/<type_>', methods=['GET'])
@jwt_required()
def get_integration_detail(type_):
    """Детальная страница интеграции — settings + текущий run + история."""
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    if not _valid_type(type_):
        return jsonify({'success': False, 'message': 'Неизвестный тип'}), 404

    settings = _get_or_create_settings(type_)
    active_run = IntegrationRun.query.filter_by(type=type_, status='running').first()
    history = (
        IntegrationRun.query.filter_by(type=type_)
        .order_by(desc(IntegrationRun.started_at))
        .limit(30)
        .all()
    )
    return jsonify({
        'success': True,
        'data': {
            'type': type_,
            'online': _is_online(settings),
            'settings': settings.to_dict(),
            'active_run': active_run.to_dict() if active_run else None,
            'history': [r.to_dict() for r in history],
        },
    }), 200


@integrations_bp.route('/<type_>/settings', methods=['PUT'])
@jwt_required()
def update_integration_settings(type_):
    """Сохранить расписание/enabled."""
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    if not _valid_type(type_):
        return jsonify({'success': False, 'message': 'Неизвестный тип'}), 404

    data = request.get_json() or {}
    settings = _get_or_create_settings(type_)

    if 'enabled' in data:
        settings.enabled = bool(data['enabled'])
    if 'schedule_mode' in data:
        if data['schedule_mode'] not in SCHEDULE_MODES:
            return jsonify({'success': False, 'message': f'schedule_mode должен быть одним из {SCHEDULE_MODES}'}), 400
        settings.schedule_mode = data['schedule_mode']
    if 'schedule_data' in data:
        if not isinstance(data['schedule_data'], dict):
            return jsonify({'success': False, 'message': 'schedule_data должно быть объектом'}), 400
        settings.schedule_data = data['schedule_data']

    db.session.commit()
    return jsonify({'success': True, 'data': settings.to_dict()}), 200


@integrations_bp.route('/<type_>/trigger', methods=['POST'])
@jwt_required()
def trigger_integration(type_):
    """Кнопка «Запустить сейчас» — ставит команду в очередь для воркера."""
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    if not _valid_type(type_):
        return jsonify({'success': False, 'message': 'Неизвестный тип'}), 404

    # Не даём поставить вторую команду если уже идёт run — избегаем гонки.
    active = IntegrationRun.query.filter_by(type=type_, status='running').first()
    if active:
        return jsonify({
            'success': False,
            'message': 'Уже идёт выгрузка. Дождитесь её завершения.',
            'active_run_id': active.id,
        }), 409

    # Не даём вторую pending-команду — если оператор уже нажал.
    pending = IntegrationCommand.query.filter_by(
        type=type_, command='run_now', consumed_at=None,
    ).first()
    if pending:
        return jsonify({
            'success': True,
            'message': 'Команда уже в очереди, воркер её подхватит.',
            'command_id': pending.id,
        }), 200

    jwt_data = get_jwt()
    user_email = jwt_data.get('email') or jwt_data.get('sub')
    cmd = IntegrationCommand(
        type=type_,
        command='run_now',
        created_by=user_email,
    )
    db.session.add(cmd)
    db.session.commit()
    return jsonify({'success': True, 'command_id': cmd.id}), 201


@integrations_bp.route('/<type_>/current', methods=['GET'])
@jwt_required()
def get_current_run(type_):
    """
    Обычный REST снапшот — fallback если SSE недоступен (proxy режет,
    браузер не поддерживает и т.п.) или для одноразовых чтений.
    Основной способ мониторинга — SSE через /stream (см. выше).
    """
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    if not _valid_type(type_):
        return jsonify({'success': False, 'message': 'Неизвестный тип'}), 404

    return jsonify({'success': True, 'data': _make_snapshot(type_)}), 200


@integrations_bp.route('/<type_>/stream', methods=['GET'])
def stream_integration(type_):
    """
    SSE-стрим: реалтайм состояние одной интеграции (для детальной страницы).

    Отправляемые events:
      - initial: полный снапшот {online, settings, active_run, last_run, pending_command}
      - update: тот же формат, если что-то изменилось (снапшоты сравниваются JSON-строкой)
      - ping: раз в 25 сек, чтобы прокси не убил идущее соединение

    JWT: EventSource не отправляет кастомные headers, поэтому либо принимаем
    `?token=<jwt>` query param, либо полагаемся на httpOnly-cookie
    (если фронт на том же origin через Next.js proxy).
    """
    if not _valid_type(type_):
        return jsonify({'error': 'unknown_type'}), 404

    # Аутентификация: сначала пробуем токен из query param (?token=...),
    # потом стандартный JWT (cookie или Authorization header).
    token = request.args.get('token')
    if token:
        # verify_jwt_in_request не умеет читать из query, поэтому подкладываем в header
        request.environ['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({'error': 'unauthorized'}), 401
    if not _check_admin():
        return jsonify({'error': 'forbidden'}), 403

    # Захватываем контекст приложения, чтобы генератор мог делать запросы к БД
    # уже вне request context.
    app = current_app._get_current_object()

    def event_gen():
        with app.app_context():
            last_snap_json = None
            last_ping = time.time()
            while True:
                snap = _make_snapshot(type_)
                snap_json = json.dumps(snap, ensure_ascii=False, default=str)
                event_type = 'initial' if last_snap_json is None else 'update'
                if snap_json != last_snap_json:
                    yield f'event: {event_type}\ndata: {snap_json}\n\n'
                    last_snap_json = snap_json
                    last_ping = time.time()
                # Ping для keep-alive (Render / Cloudflare могут закрыть idle 60s)
                if time.time() - last_ping > 25:
                    yield f': ping {int(time.time())}\n\n'
                    last_ping = time.time()
                time.sleep(1)

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',  # отключить буферизацию у proxy (nginx-like)
    }
    return Response(stream_with_context(event_gen()), headers=headers)


def _make_snapshot(type_):
    """Собирает полное состояние интеграции для SSE / polling ручек."""
    settings = _get_or_create_settings(type_)
    active_run = IntegrationRun.query.filter_by(type=type_, status='running').first()
    last_run = IntegrationRun.query.filter_by(type=type_).order_by(desc(IntegrationRun.started_at)).first()
    pending_cmd = IntegrationCommand.query.filter_by(
        type=type_, command='run_now', consumed_at=None,
    ).first()
    return {
        'type': type_,
        'online': _is_online(settings),
        'settings': settings.to_dict(),
        'active_run': active_run.to_dict() if active_run else None,
        'last_run': last_run.to_dict() if last_run else None,
        'pending_command': pending_cmd.to_dict() if pending_cmd else None,
    }


@integrations_bp.route('/<type_>/runs', methods=['GET'])
@jwt_required()
def list_runs(type_):
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    if not _valid_type(type_):
        return jsonify({'success': False, 'message': 'Неизвестный тип'}), 404

    limit = min(int(request.args.get('limit', 30)), 100)
    runs = (
        IntegrationRun.query.filter_by(type=type_)
        .order_by(desc(IntegrationRun.started_at))
        .limit(limit)
        .all()
    )
    return jsonify({'success': True, 'data': [r.to_dict() for r in runs]}), 200


# ============ INTERNAL endpoints (для локального воркера) ============

@integrations_bp.route('/internal/<type_>/settings', methods=['GET'])
def internal_get_settings(type_):
    """Воркер читает своё расписание при старте / после reload."""
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    if not _valid_type(type_):
        return jsonify({'error': 'unknown_type'}), 404

    settings = _get_or_create_settings(type_)
    return jsonify(settings.to_dict()), 200


@integrations_bp.route('/internal/<type_>/heartbeat', methods=['POST'])
def internal_heartbeat(type_):
    """Воркер шлёт heartbeat каждые ~5 сек. Обновляем last_heartbeat_at."""
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    if not _valid_type(type_):
        return jsonify({'error': 'unknown_type'}), 404

    settings = _get_or_create_settings(type_)
    settings.last_heartbeat_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True}), 200


@integrations_bp.route('/internal/<type_>/pending-command', methods=['GET'])
def internal_pending_command(type_):
    """
    Воркер каждые ~10 сек проверяет очередь команд.
    Отдаёт самую старую неисполненную команду и помечает её consumed_at.
    """
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    if not _valid_type(type_):
        return jsonify({'error': 'unknown_type'}), 404

    cmd = (
        IntegrationCommand.query.filter_by(type=type_, consumed_at=None)
        .order_by(IntegrationCommand.created_at)
        .first()
    )
    if cmd is None:
        return jsonify({'command': None}), 200
    cmd.consumed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'command': cmd.to_dict()}), 200


@integrations_bp.route('/internal/<type_>/run', methods=['POST'])
def internal_create_run(type_):
    """Воркер создаёт запись run'а при старте миграции."""
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    if not _valid_type(type_):
        return jsonify({'error': 'unknown_type'}), 404

    data = request.get_json() or {}
    run = IntegrationRun(
        type=type_,
        trigger=data.get('trigger', 'scheduled'),
        triggered_by=data.get('triggered_by'),
        status='running',
        phase=data.get('phase', 'starting'),
        progress=data.get('progress'),
    )
    db.session.add(run)
    db.session.commit()
    return jsonify({'id': run.id}), 201


@integrations_bp.route('/internal/<type_>/run/<int:run_id>', methods=['POST'])
def internal_update_run(type_, run_id):
    """
    Воркер обновляет прогресс/статус run'а каждые несколько секунд.
    Финальный вызов — с status='success'/'failed' и finished_at.
    """
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    if not _valid_type(type_):
        return jsonify({'error': 'unknown_type'}), 404

    run = IntegrationRun.query.filter_by(id=run_id, type=type_).first()
    if not run:
        return jsonify({'error': 'not_found'}), 404

    data = request.get_json() or {}
    if 'status' in data:
        if data['status'] not in RUN_STATUSES:
            return jsonify({'error': 'bad_status'}), 400
        run.status = data['status']
        if data['status'] != 'running' and not run.finished_at:
            run.finished_at = datetime.utcnow()
    if 'phase' in data:
        run.phase = data['phase']
    if 'progress' in data:
        run.progress = data['progress']
    if 'error' in data:
        run.error = data['error']
    if 'log_excerpt' in data:
        run.log_excerpt = data['log_excerpt']

    db.session.commit()
    return jsonify({'ok': True}), 200
