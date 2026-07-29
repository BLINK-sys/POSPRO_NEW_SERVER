"""
Endpoints для сервиса сбора данных 2GIS.

Публичная часть (JWT admin/system) — для админки:
- POST /api/admin/collector/tasks               создать задачу
- GET  /api/admin/collector/tasks               список (свои + owner видит все)
- GET  /api/admin/collector/tasks/<id>          детали + файлы
- POST /api/admin/collector/tasks/<id>/cancel   отменить
- GET  /api/admin/collector/tasks/<id>/stream   SSE прогресс + логи
- GET  /api/admin/collector/tasks/<id>/files/<fid>  прокси-скачивание с локалки
- GET  /api/admin/collector/worker              online-статус (heartbeat)
- GET  /api/admin/collector/catalog/cities?country=kz  справочник (обёртка catalogs.py)
- GET  /api/admin/collector/columns/available   DEFAULT_KEEP_COLUMNS

Internal (X-Integration-Key) — для локального воркера:
- POST /internal/collector/heartbeat
- GET  /internal/collector/next-task            берёт queued → running
- POST /internal/collector/tasks/<id>/progress  live-прогресс
- POST /internal/collector/tasks/<id>/log       строка лога
- POST /internal/collector/tasks/<id>/files     регистрирует собранный файл
- POST /internal/collector/tasks/<id>/complete  финальный статус
- GET  /internal/collector/tasks/<id>/should-stop   poll флага отмены
- GET  /internal/collector/tasks/<id>/download/<fid>  качает файл ИЗ локалки (прокси-back)
"""

import os
import json
import time
import re
import urllib.parse
from datetime import datetime

from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt, verify_jwt_in_request
from sqlalchemy import desc, or_
from werkzeug.utils import secure_filename

from extensions import db
from models.collector import (
    CollectorTask, CollectorFile, CollectorCommand, CollectorWorker,
    TASK_STATUSES, TASK_COMMANDS, FILE_FORMATS,
)
from models.systemuser import SystemUser


collector_bp = Blueprint('collector', __name__)


# ============ Config ============

INTEGRATION_KEY = os.getenv('INTEGRATION_KEY', 'CHANGE_ME_IN_ENV')
# Тот же ключ что у BIO/Equip воркера — единый секрет для всех локалка↔прод.

# Онлайн-порог. Воркер шлёт heartbeat каждые 5 сек; 20 сек = 4 пропущенных
# подряд → offline. Совпадает с BIO/Equip.
HEARTBEAT_TIMEOUT_SEC = 20

# Корень для файлов collector'а — подпапка внутри UPLOAD_FOLDER
# (см. config.py: на Render это /disk/uploads, локально <app>/uploads).
COLLECTOR_SUBFOLDER = 'collector'


def _collector_root():
    """Абсолютный путь к <UPLOAD_FOLDER>/collector/. Создаёт при отсутствии."""
    root = os.path.join(current_app.config['UPLOAD_FOLDER'], COLLECTOR_SUBFOLDER)
    os.makedirs(root, exist_ok=True)
    return root


def _task_dir(task_id):
    p = os.path.join(_collector_root(), str(task_id))
    os.makedirs(p, exist_ok=True)
    return p


# ============ Хелперы ============

def _check_admin():
    jwt_data = get_jwt()
    return jwt_data.get('role') in ('admin', 'system')


def _check_integration_key():
    key = request.headers.get('X-Integration-Key') or ''
    return key == INTEGRATION_KEY and INTEGRATION_KEY != 'CHANGE_ME_IN_ENV'


def _current_user():
    """Возвращает (user_id: int, is_owner: bool, email: str)."""
    jwt_data = get_jwt()
    sub = jwt_data.get('sub')
    try:
        uid = int(sub) if sub else None
    except (TypeError, ValueError):
        uid = None
    if uid is None:
        return None, False, None
    user = db.session.get(SystemUser, uid)
    if user is None:
        return uid, False, None
    return uid, bool(user.is_owner), user.email


def _worker():
    """Единственная запись collector_worker (id=1). Создаёт при отсутствии."""
    w = db.session.get(CollectorWorker, 1)
    if w is None:
        w = CollectorWorker(id=1)
        db.session.add(w)
        db.session.commit()
    return w


def _worker_online():
    w = _worker()
    if not w.last_heartbeat_at:
        return False
    return (datetime.utcnow() - w.last_heartbeat_at).total_seconds() < HEARTBEAT_TIMEOUT_SEC


def _parse_custom_url(url):
    """
    2GIS URL «готовый» → (city_code, query).
    Форматы:
        https://2gis.kz/astana/search/кофейня
        https://2gis.kz/astana/search/кофейня%20алматы?...
        https://2gis.ru/moscow/search/кофейня/filters/...

    Возвращает (city, query) или (None, None) если не смогли.
    """
    if not url:
        return None, None
    try:
        parsed = urllib.parse.urlparse(url)
        parts = [p for p in parsed.path.split('/') if p]
        # Ожидаем: [city, 'search', query, ...]
        if len(parts) >= 3 and parts[1] == 'search':
            city = parts[0]
            query = urllib.parse.unquote(parts[2])
            return city, query
    except Exception:
        pass
    return None, None


def _validate_task_input(data):
    """Проверяет входные данные задачи. Возвращает список ошибок (пуст → ок)."""
    errors = []
    name = (data.get('name') or '').strip()
    if not name:
        errors.append('Название задачи обязательно.')
    elif len(name) > 200:
        errors.append('Название длиннее 200 символов.')

    custom_url = (data.get('custom_url') or '').strip() or None
    cities = data.get('cities') or []
    queries = data.get('queries') or []

    if not custom_url:
        if not isinstance(cities, list) or not cities:
            errors.append('Не выбрано ни одного города (или задайте custom_url).')
        if not isinstance(queries, list) or not queries:
            errors.append('Не задано ни одного поискового запроса (или задайте custom_url).')
    else:
        c, q = _parse_custom_url(custom_url)
        if not c or not q:
            errors.append(
                'Не удалось распознать URL 2GIS — ожидается вид '
                'https://2gis.<домен>/<город>/search/<запрос>.')

    if data.get('file_format') and data['file_format'] not in FILE_FORMATS:
        errors.append(f'file_format должен быть одним из {FILE_FORMATS}.')

    keep_columns = data.get('keep_columns')
    if keep_columns is not None and not isinstance(keep_columns, list):
        errors.append('keep_columns должно быть массивом строк или null.')

    for k in ('delay_min_ms', 'delay_max_ms'):
        v = data.get(k)
        if v is not None and (not isinstance(v, int) or v < 0):
            errors.append(f'{k} должно быть неотрицательным целым.')

    return errors


# ============ ADMIN endpoints ============

@collector_bp.route('/tasks', methods=['POST'])
@jwt_required()
def create_task():
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    uid, _, _ = _current_user()
    if uid is None:
        return jsonify({'success': False, 'message': 'Пользователь не найден'}), 401

    data = request.get_json() or {}
    errors = _validate_task_input(data)
    if errors:
        return jsonify({'success': False, 'message': '; '.join(errors)}), 400

    custom_url = (data.get('custom_url') or '').strip() or None
    cities = data.get('cities') or []
    queries = data.get('queries') or []
    if custom_url:
        c, q = _parse_custom_url(custom_url)
        cities = [c]
        queries = [q]

    task = CollectorTask(
        owner_id=uid,
        name=(data.get('name') or '').strip(),
        cities=cities,
        queries=queries,
        custom_url=custom_url,
        keep_columns=data.get('keep_columns'),
        drop_other_columns=bool(data.get('drop_other_columns', True)),
        autosize_columns=bool(data.get('autosize_columns', True)),
        wrap_text=bool(data.get('wrap_text', False)),
        networks_min_count=data.get('networks_min_count'),
        sort_by_name=bool(data.get('sort_by_name', False)),
        max_records=data.get('max_records'),
        file_format=data.get('file_format', 'xlsx'),
        delay_min_ms=data.get('delay_min_ms', 3000),
        delay_max_ms=data.get('delay_max_ms', 5000),
        status='queued',
    )
    db.session.add(task)
    db.session.flush()  # получить id

    jwt_data = get_jwt()
    email = None
    try:
        user = db.session.get(SystemUser, int(jwt_data.get('sub'))) if jwt_data.get('sub') else None
        email = user.email if user else None
    except (TypeError, ValueError):
        pass

    # Кладём run_now в очередь команд для воркера.
    db.session.add(CollectorCommand(
        task_id=task.id, command='run_now', created_by=email,
    ))
    db.session.commit()

    return jsonify({'success': True, 'data': _enrich_task_dict(task.to_dict())}), 201


@collector_bp.route('/tasks', methods=['GET'])
@jwt_required()
def list_tasks():
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    uid, is_owner, _ = _current_user()

    q = CollectorTask.query
    if not is_owner:
        q = q.filter_by(owner_id=uid)

    # Фильтры
    status = request.args.get('status')
    if status and status in TASK_STATUSES:
        q = q.filter(CollectorTask.status == status)

    limit = min(int(request.args.get('limit', 50)), 200)
    q = q.order_by(desc(CollectorTask.created_at)).limit(limit)

    result = []
    for t in q.all():
        d = _enrich_task_dict(t.to_dict())
        # Добавим короткую сводку по файлам без полного списка.
        files_ok = sum(1 for f in t.files if f.status == 'ok')
        d['files_count'] = len(t.files)
        d['files_ok'] = files_ok
        result.append(d)

    return jsonify({'success': True, 'data': result, 'online': _worker_online()}), 200


@collector_bp.route('/tasks/<int:task_id>', methods=['GET'])
@jwt_required()
def get_task(task_id):
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    uid, is_owner, _ = _current_user()

    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'success': False, 'message': 'Не найдено'}), 404
    if not is_owner and task.owner_id != uid:
        return jsonify({'success': False, 'message': 'Нет доступа'}), 403

    return jsonify({
        'success': True,
        'data': _enrich_task_dict(task.to_dict(include_files=True)),
        'online': _worker_online(),
    }), 200


@collector_bp.route('/tasks/<int:task_id>/cancel', methods=['POST'])
@jwt_required()
def cancel_task(task_id):
    """
    Отмена:
      - queued без старта → status='cancelled' сразу (воркер увидит при next-task
        и пропустит), а сам pending run_now удаляется.
      - running → cancel-команда в очередь (воркер поймает по should-stop
        и мягко остановит collect() на ближайшей карточке).
      - pending run_now (ещё не подхвачен) → удаляем команду.
    """
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    uid, is_owner, email = _current_user()

    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'success': False, 'message': 'Не найдено'}), 404
    if not is_owner and task.owner_id != uid:
        return jsonify({'success': False, 'message': 'Нет доступа'}), 403

    if task.status in ('success', 'failed', 'cancelled'):
        return jsonify({'success': False, 'message': 'Задача уже завершена'}), 400

    actions = []

    pending_run = CollectorCommand.query.filter_by(
        task_id=task_id, command='run_now', consumed_at=None,
    ).first()
    if pending_run:
        db.session.delete(pending_run)
        actions.append('pending run_now removed')

    if task.status == 'queued':
        # Воркер ещё не начал — помечаем сразу.
        task.status = 'cancelled'
        task.finished_at = datetime.utcnow()
        task.error = f'Отменено пользователем {email or uid} до старта'
        actions.append('queued cancelled')
    elif task.status == 'running':
        # Дедупликация: уже есть неисполненная cancel-команда — не плодим.
        exists = CollectorCommand.query.filter_by(
            task_id=task_id, command='cancel', consumed_at=None,
        ).first()
        if not exists:
            db.session.add(CollectorCommand(
                task_id=task_id, command='cancel', created_by=email,
            ))
        actions.append('cancel signal queued')

    db.session.commit()
    return jsonify({'success': True, 'message': '; '.join(actions) or 'noop'}), 200


@collector_bp.route('/tasks/<int:task_id>/stream', methods=['GET'])
def stream_task(task_id):
    """
    SSE-стрим прогресса. JWT читается из ?token= query (EventSource не умеет
    кастомные заголовки). Полностью аналогично integrations/<type>/stream.
    """
    token = request.args.get('token')
    if token:
        request.environ['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({'error': 'unauthorized'}), 401
    if not _check_admin():
        return jsonify({'error': 'forbidden'}), 403

    uid, is_owner, _ = _current_user()
    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'error': 'not_found'}), 404
    if not is_owner and task.owner_id != uid:
        return jsonify({'error': 'forbidden'}), 403

    app = current_app._get_current_object()

    def event_gen():
        with app.app_context():
            last_snap = None
            last_ping = time.time()
            while True:
                # expire_all ПЕРЕД каждым .get(): без этого SQLAlchemy
                # identity map отдаёт закэшированный объект, воркер обновляет
                # запись из другого коннекта — а UI получает начальный
                # snapshot и потом «замирает» до перезагрузки страницы.
                # Аналогично протухают `t.files` (lazy relationship) — expire
                # сбрасывает и их.
                db.session.expire_all()
                t = db.session.get(CollectorTask, task_id)
                if t is None:
                    yield 'event: gone\ndata: {}\n\n'
                    break
                snap = _enrich_task_dict(t.to_dict(include_files=True))
                snap['online'] = _worker_online()
                snap_json = json.dumps(snap, ensure_ascii=False, default=str)
                event_type = 'initial' if last_snap is None else 'update'
                if snap_json != last_snap:
                    yield f'event: {event_type}\ndata: {snap_json}\n\n'
                    last_snap = snap_json
                    last_ping = time.time()
                if time.time() - last_ping > 25:
                    yield f': ping {int(time.time())}\n\n'
                    last_ping = time.time()

                # Как только задача финальная — можно попрощаться сразу,
                # ждать нечего. UI успеет получить последний snap.
                if t.status in ('success', 'failed', 'cancelled'):
                    yield 'event: finished\ndata: {}\n\n'
                    break

                time.sleep(1)

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    }
    return Response(stream_with_context(event_gen()), headers=headers)


@collector_bp.route('/tasks/<int:task_id>/files/<int:file_id>', methods=['GET'])
@jwt_required()
def download_file(task_id, file_id):
    """
    Скачивание — файл лежит на persistent-диске Render (`/disk/uploads/collector/`).
    Локалка после сборки каждой пары push'ит файл через `/internal/.../files`
    (multipart), прод сохраняет на диск, здесь просто отдаём его через send_file.
    """
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    uid, is_owner, _ = _current_user()

    file_row = db.session.get(CollectorFile, file_id)
    if not file_row or file_row.task_id != task_id:
        return jsonify({'success': False, 'message': 'Файл не найден'}), 404
    if not is_owner and file_row.task.owner_id != uid:
        return jsonify({'success': False, 'message': 'Нет доступа'}), 403
    if file_row.status != 'ok' or not file_row.rel_path:
        return jsonify({'success': False, 'message': 'Файл не готов'}), 400

    abs_path = os.path.join(_collector_root(), file_row.rel_path)
    if not os.path.exists(abs_path):
        return jsonify({'success': False, 'message': 'Файл на диске не найден'}), 410

    fname = file_row.filename or os.path.basename(abs_path)
    return send_file(
        abs_path,
        as_attachment=True,
        download_name=fname,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        if fname.lower().endswith('.xlsx') else 'application/octet-stream',
    )


@collector_bp.route('/worker', methods=['GET'])
@jwt_required()
def worker_status():
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    w = _worker()
    return jsonify({
        'success': True,
        'online': _worker_online(),
        'data': w.to_dict(),
    }), 200


# Справочник городов Казахстана — захардкожен в бэке, чтобы не тащить
# gis2_collector на Render (либа нужна только воркеру на локалке). Взято
# из cities.json в gis2_collector/engine/data + CITY_CODE_OVERRIDES:
#   * nur_sultan → astana (подтверждено выгрузкой 1248 записей по Астане)
#   * kyzylorda в справочнике либы стоит с domain=ru — реально работает
#     как 2gis.kz/kyzylorda, поэтому здесь домен kz.
COLLECTOR_CITIES_KZ = [
    {'code': 'aktau',         'name': 'Актау',            'domain': 'kz'},
    {'code': 'aktobe',        'name': 'Актобе',           'domain': 'kz'},
    {'code': 'almaty',        'name': 'Алматы',           'domain': 'kz'},
    {'code': 'astana',        'name': 'Астана',           'domain': 'kz'},
    {'code': 'atyrau',        'name': 'Атырау',           'domain': 'kz'},
    {'code': 'ekibastuz',     'name': 'Экибастуз',        'domain': 'kz'},
    {'code': 'zhezkazgan',    'name': 'Жезказган',        'domain': 'kz'},
    {'code': 'karaganda',     'name': 'Караганда',        'domain': 'kz'},
    {'code': 'kokshetau',     'name': 'Кокшетау',         'domain': 'kz'},
    {'code': 'kostanay',      'name': 'Костанай',         'domain': 'kz'},
    {'code': 'kyzylorda',     'name': 'Кызылорда',        'domain': 'kz'},
    {'code': 'pavlodar',      'name': 'Павлодар',         'domain': 'kz'},
    {'code': 'petropavlovsk', 'name': 'Петропавловск',    'domain': 'kz'},
    {'code': 'semey',         'name': 'Семей',            'domain': 'kz'},
    {'code': 'shymkent',      'name': 'Шымкент',          'domain': 'kz'},
    {'code': 'taraz',         'name': 'Тараз',            'domain': 'kz'},
    {'code': 'turkestan',     'name': 'Туркестан',        'domain': 'kz'},
    {'code': 'uralsk',        'name': 'Уральск',          'domain': 'kz'},
    {'code': 'ustkam',        'name': 'Усть-Каменогорск', 'domain': 'kz'},
]

COLLECTOR_CITIES = {
    'kz': COLLECTOR_CITIES_KZ,
}

# Быстрый lookup code → русское имя (для резолвинга при отдаче задач).
_CITY_CODE_TO_NAME: dict[str, str] = {}
for _country_cities in COLLECTOR_CITIES.values():
    for _c in _country_cities:
        _CITY_CODE_TO_NAME[_c['code']] = _c['name']


def _resolve_city_names(codes):
    """['astana', 'almaty', 'foo'] → ['Астана', 'Алматы', 'foo']."""
    if not codes:
        return []
    return [_CITY_CODE_TO_NAME.get(c, c) for c in codes]


def _enrich_task_dict(d: dict) -> dict:
    """Добавляет city_names — русские названия для UI, без второго роунд-трипа."""
    d['city_names'] = _resolve_city_names(d.get('cities') or [])
    return d


@collector_bp.route('/catalog/cities', methods=['GET'])
@jwt_required()
def catalog_cities():
    """
    Справочник городов для формы создания задачи. Отдаём хардкод чтобы не
    тащить gis2_collector на прод. При добавлении новых стран — расширить
    COLLECTOR_CITIES.
    """
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    country = (request.args.get('country') or 'kz').lower()
    data = list(COLLECTOR_CITIES.get(country, []))
    data.sort(key=lambda x: x['name'])
    return jsonify({'success': True, 'data': data}), 200


@collector_bp.route('/columns/available', methods=['GET'])
@jwt_required()
def columns_available():
    """Список стандартных колонок для галочек в форме создания задачи."""
    if not _check_admin():
        return jsonify({'success': False, 'message': 'Доступ запрещён'}), 403
    # Хардкодим тот же список что в gis2_collector.DEFAULT_KEEP_COLUMNS —
    # не форсим импорт (gis2_collector не установлен на прод, см. выше).
    default_columns = [
        'Наименование',
        'Город',
        'Телефон 1',
        'E-mail',
        'Instagram',
        'WhatsApp 1',
        '2GIS URL',
    ]
    # Дополнительные, которые бывают в выгрузке 2GIS.
    extra_columns = [
        'Адрес',
        'Телефон 2',
        'Телефон 3',
        'Сайт',
        'Facebook',
        'ВКонтакте',
        'Telegram',
        'Часы работы',
        'Категория',
        'Рубрика',
    ]
    return jsonify({
        'success': True,
        'data': {
            'default': default_columns,
            'extra': extra_columns,
        },
    }), 200


# ============ INTERNAL endpoints (для воркера) ============

@collector_bp.route('/internal/heartbeat', methods=['POST'])
def internal_heartbeat():
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True) or {}
    w = _worker()
    w.last_heartbeat_at = datetime.utcnow()
    if data.get('hostname'):
        w.hostname = str(data['hostname'])[:200]
    db.session.commit()
    return jsonify({'ok': True}), 200


@collector_bp.route('/internal/next-task', methods=['GET'])
def internal_next_task():
    """
    Воркер поллит эту ручку. Логика:
      1. Ищем самую старую consumed=NULL команду run_now.
       Помечаем consumed_at.
      2. Проверяем задачу: если уже cancelled/success/failed — пропускаем
         (и повторяем поиск), возвращаем следующую.
      3. Если ок — переводим task.status queued→running, started_at=now.
      4. Возвращаем {task: {...}} для воркера.
    """
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403

    # Достаём команды по очереди пока не найдём валидную задачу.
    while True:
        cmd = (
            CollectorCommand.query
            .filter_by(command='run_now', consumed_at=None)
            .order_by(CollectorCommand.created_at)
            .first()
        )
        if cmd is None:
            return jsonify({'task': None}), 200

        cmd.consumed_at = datetime.utcnow()
        task = db.session.get(CollectorTask, cmd.task_id)

        if task is None or task.status in ('cancelled', 'success', 'failed'):
            # Задача уже недействительна, коммитим consume и берём следующую.
            db.session.commit()
            continue

        task.status = 'running'
        task.started_at = datetime.utcnow()
        task.phase = 'starting'
        db.session.commit()
        return jsonify({'task': task.to_dict()}), 200


@collector_bp.route('/internal/tasks/<int:task_id>/progress', methods=['POST'])
def internal_progress(task_id):
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'error': 'not_found'}), 404
    data = request.get_json() or {}
    if 'phase' in data:
        task.phase = data['phase']
    if 'progress' in data:
        task.progress = data['progress']
    db.session.commit()
    return jsonify({'ok': True}), 200


@collector_bp.route('/internal/tasks/<int:task_id>/log', methods=['POST'])
def internal_log(task_id):
    """
    Дописывает строку в log_excerpt. Держим лимит ~8000 симв — SSE не любит
    гонять весь простыню лога.
    """
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'error': 'not_found'}), 404
    data = request.get_json() or {}
    line = str(data.get('line') or '')
    if not line:
        return jsonify({'ok': True}), 200

    ts = datetime.utcnow().strftime('%H:%M:%S')
    existing = task.log_excerpt or ''
    combined = existing + f'[{ts}] {line}\n'
    # Обрезаем до последних ~8000 символов, чтобы не разрастаться.
    if len(combined) > 8000:
        combined = combined[-8000:]
    task.log_excerpt = combined
    db.session.commit()
    return jsonify({'ok': True}), 200


@collector_bp.route('/internal/tasks/<int:task_id>/files', methods=['POST'])
def internal_add_file(task_id):
    """
    Воркер регистрирует один собранный файл после завершения пары.
    Формат — multipart/form-data:
      - `metadata` (application/json): {city, query, url, rows, bytes,
        attempts, duration_sec, status, error, filename, city_name}
      - `file` (application/octet-stream, опционально): сам .xlsx.
        Отсутствует если status != 'ok'.
    """
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'error': 'not_found'}), 404

    # metadata может прийти как form field ИЛИ как json (fallback для тестов).
    if 'metadata' in request.form:
        try:
            data = json.loads(request.form['metadata'])
        except ValueError:
            return jsonify({'error': 'bad_metadata_json'}), 400
    else:
        data = request.get_json(silent=True) or {}

    status = data.get('status', 'failed')
    filename = data.get('filename') or ''

    rel_path = None
    saved_bytes = 0
    upload = request.files.get('file')
    if upload and status == 'ok':
        # Безопасное имя. Русские буквы secure_filename съедает, поэтому
        # переводим в транслит-безопасный вид только по крайней нужде;
        # для UI имя красивое из `filename` в базе, а на диске — safe.
        safe_name = secure_filename(filename) or f'file_{int(time.time() * 1000)}.xlsx'
        target_dir = _task_dir(task_id)
        abs_path = os.path.join(target_dir, safe_name)
        # Если совпадение имени по разным парам — добавляем суффикс.
        base, ext = os.path.splitext(abs_path)
        i = 1
        while os.path.exists(abs_path):
            abs_path = f'{base}_{i}{ext}'
            i += 1
        upload.save(abs_path)
        saved_bytes = os.path.getsize(abs_path)
        rel_path = os.path.relpath(abs_path, _collector_root()).replace('\\', '/')

    file_row = CollectorFile(
        task_id=task_id,
        city=data.get('city', ''),
        city_name=data.get('city_name'),
        query=data.get('query', ''),
        url=data.get('url', ''),
        rel_path=rel_path,
        filename=filename or None,
        rows=int(data.get('rows', 0)),
        bytes=int(data.get('bytes', saved_bytes) or saved_bytes),
        attempts=int(data.get('attempts', 0)),
        duration_sec=float(data.get('duration_sec', 0)),
        status=status,
        error=data.get('error'),
    )
    db.session.add(file_row)
    db.session.commit()
    return jsonify({'ok': True, 'id': file_row.id, 'rel_path': rel_path}), 201


@collector_bp.route('/internal/tasks/<int:task_id>/complete', methods=['POST'])
def internal_complete(task_id):
    """Финальный тик от воркера — status='success'/'failed'/'cancelled'."""
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    task = db.session.get(CollectorTask, task_id)
    if not task:
        return jsonify({'error': 'not_found'}), 404
    data = request.get_json() or {}

    status = data.get('status', 'success')
    if status not in TASK_STATUSES:
        return jsonify({'error': 'bad_status'}), 400
    task.status = status
    task.finished_at = datetime.utcnow()
    if 'error' in data:
        task.error = data['error']
    if 'phase' in data:
        task.phase = data['phase']
    if 'progress' in data:
        task.progress = data['progress']
    db.session.commit()
    return jsonify({'ok': True}), 200


@collector_bp.route('/internal/tasks/<int:task_id>/should-stop', methods=['GET'])
def internal_should_stop(task_id):
    """
    Воркер опрашивает эту ручку каждые ~2 сек в отдельном потоке во время
    collect(). Отдаёт true, если есть пенднинг cancel-команда — воркер
    поставит флаг для should_stop колбэка и остановится на карточке.
    """
    if not _check_integration_key():
        return jsonify({'error': 'forbidden'}), 403
    exists = CollectorCommand.query.filter_by(
        task_id=task_id, command='cancel', consumed_at=None,
    ).first()
    if exists:
        # Помечаем cancel как consumed, чтобы после рестарта воркера не
        # прилетел повтор.
        exists.consumed_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'stop': True}), 200
    return jsonify({'stop': False}), 200
