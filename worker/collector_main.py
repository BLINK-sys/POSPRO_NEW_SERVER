"""
Локальный воркер 2GIS-сбора. Живёт на резервном ПК
(`R:\\integration\\collector\\worker\\collector_main.py`), запускается
Task Scheduler'ом при логоне юзера Алина — не Windows Service, потому что
`gis2_collector.collect()` с `headless=False` требует живой desktop-сессии.

Взаимодействие с прод-магазином — только исходящее HTTP на
`/api/admin/collector/internal/*` с заголовком `X-Integration-Key`.

Единственный consumer: пока `collect()` не завершится, следующая задача
ждёт (FIFO). Параллельность не нужна — резервный ПК слабый, и один Chrome
за раз проще чем два.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv


# ── Config ──────────────────────────────────────────────────────────

WORKER_DIR = Path(__file__).resolve().parent
# Ожидаем структуру:
#   R:\integration\collector\
#     ├── worker\collector_main.py    <- этот файл
#     ├── gis2_collector\             <- код либы, git clone POSPRO_NEW_SERVER подпапка collector\
#     ├── outputs\                    <- сюда collect() кладёт .xlsx
#     ├── .venv\                      <- Python окружение
#     └── worker\.env                 <- секреты
COLLECTOR_ROOT = WORKER_DIR.parent
LOG_DIR = WORKER_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

load_dotenv(WORKER_DIR / '.env')

API_URL = os.getenv('POSPRO_API_URL', 'https://pospro-new-server.onrender.com').rstrip('/')
INTEGRATION_KEY = os.getenv('INTEGRATION_KEY', '')
LOG_LEVEL = os.getenv('WORKER_LOG_LEVEL', 'INFO').upper()

HEARTBEAT_INTERVAL = 5           # сек — 3× совпадает с BIO/Equip
COMMAND_POLL_INTERVAL = 10       # сек — polling next-task
STOP_POLL_INTERVAL = 2           # сек — polling should-stop во время collect()

# retry backoff — те же значения что у BIO/Equip воркера.
BACKOFF_MAX = 30
LOG_FAILURE_EVERY_SEC = 60

OUTPUT_DIR = COLLECTOR_ROOT / 'outputs'
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Logging ─────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / 'collector_worker.log', encoding='utf-8'),
    ],
)
log = logging.getLogger('collector_worker')

# gis2_collector — либо установлен в venv (pip install -e ../gis2_collector),
# либо просто добавляем родительскую папку в sys.path.
sys.path.insert(0, str(COLLECTOR_ROOT))


# ── HTTP клиент ─────────────────────────────────────────────────────

class Client:
    def __init__(self):
        self.base = f'{API_URL}/api/admin/collector/internal'
        self.headers = {'X-Integration-Key': INTEGRATION_KEY}
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f'{self.base}/{path.lstrip("/")}'

    def heartbeat(self, hostname: str) -> bool:
        try:
            r = self.session.post(self._url('heartbeat'),
                                  json={'hostname': hostname},
                                  headers=self.headers, timeout=10)
            return r.ok
        except Exception:
            return False

    def next_task(self) -> Optional[dict]:
        try:
            r = self.session.get(self._url('next-task'), headers=self.headers, timeout=15)
            if r.ok:
                return r.json().get('task')
        except Exception:
            pass
        return None

    def progress(self, task_id: int, **fields) -> bool:
        try:
            r = self.session.post(self._url(f'tasks/{task_id}/progress'),
                                  json=fields, headers=self.headers, timeout=10)
            return r.ok
        except Exception:
            return False

    def log_line(self, task_id: int, line: str) -> bool:
        try:
            r = self.session.post(self._url(f'tasks/{task_id}/log'),
                                  json={'line': line}, headers=self.headers, timeout=10)
            return r.ok
        except Exception:
            return False

    def complete(self, task_id: int, status: str, error: Optional[str] = None,
                 phase: Optional[str] = None, progress: Optional[dict] = None) -> bool:
        body = {'status': status}
        if error is not None: body['error'] = error
        if phase is not None: body['phase'] = phase
        if progress is not None: body['progress'] = progress
        try:
            r = self.session.post(self._url(f'tasks/{task_id}/complete'),
                                  json=body, headers=self.headers, timeout=30)
            return r.ok
        except Exception as e:
            log.warning('complete failed: %s', e)
            return False

    def should_stop(self, task_id: int) -> bool:
        try:
            r = self.session.get(self._url(f'tasks/{task_id}/should-stop'),
                                 headers=self.headers, timeout=10)
            if r.ok:
                return bool(r.json().get('stop'))
        except Exception:
            pass
        return False

    def upload_file(self, task_id: int, meta: dict, abs_path: Optional[str] = None) -> Optional[dict]:
        """
        Регистрирует файл на проде. Если abs_path задан и файл существует —
        multipart с самим xlsx. Иначе только метаданные (для failed/stopped).
        """
        try:
            data = {'metadata': (None, json.dumps(meta, ensure_ascii=False), 'application/json')}
            files = None
            if abs_path and os.path.exists(abs_path):
                fname = os.path.basename(abs_path)
                files = {
                    'metadata': (None, json.dumps(meta, ensure_ascii=False), 'application/json'),
                    'file': (fname, open(abs_path, 'rb'), 'application/octet-stream'),
                }
                r = self.session.post(self._url(f'tasks/{task_id}/files'),
                                      files=files, headers=self.headers, timeout=(10, 120))
            else:
                r = self.session.post(self._url(f'tasks/{task_id}/files'),
                                      files=data, headers=self.headers, timeout=30)
            if r.ok:
                return r.json()
        except Exception as e:
            log.warning('upload_file failed: %s', e)
        return None


client = Client()


# ── Task Runner ─────────────────────────────────────────────────────


class TaskRunner:
    """
    Обёртка над gis2_collector.collect().
    Собирает CollectTask из данных прод-задачи, гоняет sync-цикл в текущем
    потоке (consumer уже в своём треде), заодно держит фоновый поллинг
    should-stop и стример прогресса.
    """

    def __init__(self, task_data: dict):
        self.task = task_data
        self.task_id = int(task_data['id'])
        self.stop_flag = threading.Event()
        self._stop_poller: Optional[threading.Thread] = None

    # ── Управление should-stop поллером ──
    def _stop_poll_loop(self) -> None:
        while not self.stop_flag.is_set():
            if client.should_stop(self.task_id):
                log.info('[task %d] cancel сигнал получен, ставлю stop_flag', self.task_id)
                self.stop_flag.set()
                return
            time.sleep(STOP_POLL_INTERVAL)

    def _start_stop_poller(self) -> None:
        self._stop_poller = threading.Thread(
            target=self._stop_poll_loop, name=f'stop_poll_{self.task_id}', daemon=True,
        )
        self._stop_poller.start()

    # ── on_progress колбэк от collect() ──
    def _on_progress(self, event) -> None:
        """
        Обработчик gis2_collector.ProgressEvent'ов. Мапим в:
          - progress JSON для UI (текущая пара, счётчик записей, фаза)
          - log_line для событий уровня INFO/WARNING/ERROR
        Троттлим update'ы progress'а: гоняем на каждый record не имеет смысла,
        серверу и так тяжко.
        """
        kind = event.kind
        # log — сразу пробрасываем
        if kind == 'log':
            level = (event.level or 'INFO').upper()
            if level in ('WARNING', 'ERROR', 'CRITICAL'):
                client.log_line(self.task_id, f'[{level}] {event.message}')
            elif level == 'INFO':
                # Info — только если сообщение не пустое (движок много спамит)
                if event.message:
                    client.log_line(self.task_id, event.message)
            return

        # Обновление прогресса
        progress = {
            'pair_index': event.pair_index,
            'pair_total': event.pair_total,
            'city': event.city,
            'query': event.query,
            'attempt': event.attempt,
            'records': event.records,
            'message': event.message,
            'kind': kind,
        }
        phase = None
        if kind == 'task_started':
            phase = 'starting'
        elif kind == 'pair_started':
            phase = 'pair_started'
        elif kind == 'attempt_started':
            phase = 'collecting'
        elif kind == 'record':
            phase = 'collecting'
        elif kind == 'pair_finished':
            phase = 'pair_finished'
        elif kind == 'task_stopped':
            phase = 'stopping'
        elif kind == 'task_finished':
            phase = 'done'

        # Троттл: событие 'record' идёт по каждой карточке — шлём каждое 10-е.
        if kind == 'record' and event.records and event.records % 10 != 0:
            return

        client.progress(self.task_id, phase=phase, progress=progress)

        # Также раз в 10 record'ов пишем строку лога, чтобы юзер видел «идёт».
        if kind == 'record' and event.records and event.records % 50 == 0:
            client.log_line(self.task_id, f'  собрано {event.records} записей')

    def _should_stop(self) -> bool:
        return self.stop_flag.is_set()

    # ── Основной запуск ──
    def run(self) -> str:
        """Возвращает финальный статус: success/failed/cancelled."""
        from gis2_collector import CollectTask, PostprocessOptions, collect

        t = self.task
        # Формируем CollectTask из прод-задачи. Если задан custom_url —
        # прод его уже распарсил в cities=[city], queries=[query].
        cities = t.get('cities') or []
        queries = t.get('queries') or []
        if not cities or not queries:
            client.log_line(self.task_id, 'Задача пустая — нет городов или запросов')
            return 'failed'

        try:
            post = PostprocessOptions(
                keep_columns=t.get('keep_columns'),
                drop_other_columns=bool(t.get('drop_other_columns', True)),
                autosize_columns=bool(t.get('autosize_columns', True)),
                networks_min_count=t.get('networks_min_count'),
                sort_by_name=bool(t.get('sort_by_name', False)),
            )
        except Exception as e:
            client.log_line(self.task_id, f'PostprocessOptions invalid: {e}')
            return 'failed'

        # Директория для этой задачи. Файлы имеют путь
        # OUTPUT_DIR/<task_id>/<query>/<city>.xlsx (см. path_template).
        task_out = OUTPUT_DIR / str(self.task_id)
        task_out.mkdir(parents=True, exist_ok=True)

        collect_task = CollectTask(
            cities=cities,
            queries=queries,
            output_dir=task_out,
            path_template='{query_slug}/{city}',
            file_format=t.get('file_format', 'xlsx'),
            max_records=t.get('max_records'),
            delay_min_ms=int(t.get('delay_min_ms', 3000)),
            delay_max_ms=int(t.get('delay_max_ms', 5000)),
            headless=False,  # антибот 2GIS строже к headless
            postprocess=post,
        )

        client.log_line(self.task_id,
                        f'Старт: {len(cities)} г. × {len(queries)} запр. = '
                        f'{len(cities) * len(queries)} пар')

        self._start_stop_poller()

        try:
            result = collect(collect_task,
                             on_progress=self._on_progress,
                             should_stop=self._should_stop)
        except Exception as e:
            log.exception('[task %d] collect() crashed: %s', self.task_id, e)
            client.log_line(self.task_id, f'КРИТИЧНО: {type(e).__name__}: {e}')
            self.stop_flag.set()
            return 'failed'
        finally:
            self.stop_flag.set()  # финиш стоп-поллера

        # Заливаем результаты — по одному файлу на пару.
        for cf in result.files:
            meta = {
                'city': cf.city,
                'city_name': cf.city_name,
                'query': cf.query,
                'url': cf.url,
                'rows': cf.rows,
                'bytes': cf.bytes,
                'attempts': cf.attempts,
                'duration_sec': cf.duration_sec,
                'status': cf.status,
                'error': cf.error,
                'filename': f'{cf.city_name or cf.city}_{cf.query}.xlsx'.replace('/', '_')[:280],
            }
            abs_path = str(cf.path) if cf.path else None
            resp = client.upload_file(self.task_id, meta, abs_path)
            if resp is None:
                client.log_line(self.task_id,
                                f'Не удалось залить файл {cf.city}/{cf.query} — retry?')

        # Определяем финальный статус.
        cancelled_seen = self.stop_flag.is_set()
        if cancelled_seen and any(cf.status == 'stopped' for cf in result.files):
            return 'cancelled'
        if all(cf.status == 'ok' for cf in result.files) and result.files:
            return 'success'
        if any(cf.status == 'ok' for cf in result.files):
            # Часть удалась — считаем success, ошибки видно в файлах.
            return 'success'
        return 'failed'


# ── Consumer thread ─────────────────────────────────────────────────


class Orchestrator:
    """
    Единственный consumer тред: тянет задачи из /next-task, гоняет TaskRunner
    последовательно. Второй тред — heartbeat. Всё.

    В отличие от integration-воркера (BIO/Equip), тут нет FIFO очереди
    в памяти — прод сам держит очередь: воркер только тянет по одной.
    """

    def __init__(self):
        self.stop_event = threading.Event()
        self.hostname = socket.gethostname()

    def _safe_loop(self, target, name: str) -> None:
        while not self.stop_event.is_set():
            try:
                target()
                return
            except Exception as e:
                log.exception('loop %s CRASHED, рестарт через 5 сек: %s', name, e)
                self.stop_event.wait(5)

    def _sleep_with_backoff(self, loop_name: str, base_interval: int,
                            success: bool, state: dict) -> None:
        now = time.time()
        if success:
            if state.get('was_failing'):
                downtime = now - state.get('first_fail_at', now)
                log.info('%s: связь восстановлена (даунтайм %.0f сек)', loop_name, downtime)
            state.update({'was_failing': False, 'last_log_at': 0, 'first_fail_at': 0,
                          'backoff': base_interval})
            interval = base_interval
        else:
            if not state.get('was_failing'):
                log.warning('%s: связь с сервером потеряна, начинаю retry', loop_name)
                state.update({'was_failing': True, 'first_fail_at': now,
                              'last_log_at': now, 'backoff': base_interval})
            elif now - state.get('last_log_at', 0) > LOG_FAILURE_EVERY_SEC:
                downtime = now - state.get('first_fail_at', now)
                log.warning('%s: всё ещё нет связи (%.0f сек)', loop_name, downtime)
                state['last_log_at'] = now
            state['backoff'] = min(state.get('backoff', base_interval) * 2, BACKOFF_MAX)
            interval = state['backoff']
        self.stop_event.wait(interval)

    def _heartbeat_loop(self) -> None:
        state = {'was_failing': False, 'last_log_at': 0, 'first_fail_at': 0,
                 'backoff': HEARTBEAT_INTERVAL}
        while not self.stop_event.is_set():
            ok = client.heartbeat(self.hostname)
            self._sleep_with_backoff('heartbeat', HEARTBEAT_INTERVAL, ok, state)

    def _consumer_loop(self) -> None:
        state = {'was_failing': False, 'last_log_at': 0, 'first_fail_at': 0,
                 'backoff': COMMAND_POLL_INTERVAL}
        while not self.stop_event.is_set():
            task = client.next_task()
            # `next_task` возвращает None и когда нет задач, и когда прод недоступен.
            # Различать не критично — цикл всё равно ждёт следующий тик.
            if task is None:
                self._sleep_with_backoff('next-task', COMMAND_POLL_INTERVAL, True, state)
                continue

            task_id = task.get('id')
            log.info('[task %d] взял задачу: %s городов × %s запросов',
                     task_id, len(task.get('cities') or []), len(task.get('queries') or []))

            runner = TaskRunner(task)
            try:
                final_status = runner.run()
            except Exception as e:
                log.exception('[task %d] неожиданная ошибка в runner: %s', task_id, e)
                final_status = 'failed'
                client.log_line(task_id, f'КРИТИЧНО: {type(e).__name__}: {e}')

            client.complete(task_id, final_status, phase='done')
            log.info('[task %d] завершено: %s', task_id, final_status)

    def start(self) -> None:
        log.info('Collector worker starting. API=%s host=%s', API_URL, self.hostname)
        if not INTEGRATION_KEY:
            log.error('INTEGRATION_KEY не задан в .env — все запросы к серверу будут отвергнуты')
            return

        threading.Thread(target=self._safe_loop, args=(self._heartbeat_loop, 'heartbeat'),
                         daemon=True, name='heartbeat').start()
        threading.Thread(target=self._safe_loop, args=(self._consumer_loop, 'consumer'),
                         daemon=True, name='consumer').start()

        def _stop(*_):
            log.info('Received stop signal, shutting down...')
            self.stop_event.set()
            sys.exit(0)

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, _stop)

        while not self.stop_event.is_set():
            time.sleep(1)


if __name__ == '__main__':
    Orchestrator().start()
