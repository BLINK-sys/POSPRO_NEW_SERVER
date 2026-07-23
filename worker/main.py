"""
Локальный воркер автоматических выгрузок BIO/Equip.

Живёт на резервном ПК (192.168.1.99), запускается как Windows Service
через nssm. Общается с прод-сервером магазина по HTTP:
  - Heartbeat каждые 5 сек
  - GET settings каждые 60 сек (пересчёт APScheduler)
  - GET pending-command каждые 10 сек
  - Создаёт/обновляет IntegrationRun по мере работы

Локально поднимает HTTP-сервер на 127.0.0.1:9876 — скрипты миграции
шлют туда JSON-отчёты о прогрессе (см. INTEGRATION_PROGRESS_URL в env).
Воркер получает их и репортит на прод через update_run.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from flask import Flask, request, jsonify


# ── Config ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
INTEGRATION_ROOT = BASE_DIR.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

API_URL = os.getenv("POSPRO_API_URL", "https://pospro-new-server.onrender.com").rstrip("/")
INTEGRATION_KEY = os.getenv("INTEGRATION_KEY", "")
LOG_LEVEL = os.getenv("WORKER_LOG_LEVEL", "INFO").upper()

PYTHON_EXE = str(INTEGRATION_ROOT / ".venv" / "Scripts" / "python.exe")

# Локальный HTTP-сервер для приёма progress-отчётов от скриптов.
PROGRESS_HOST = "127.0.0.1"
PROGRESS_PORT = int(os.getenv("PROGRESS_PORT", "9876"))
PROGRESS_URL = f"http://{PROGRESS_HOST}:{PROGRESS_PORT}/report"

INTEGRATIONS = {
    "bio": {
        "dir": INTEGRATION_ROOT / "BioApiNewShop",
        "stage1": ["bio_api.py"],
        "stage2": ["migrate_from_products_db.py", "--yes"],
    },
    "equip": {
        "dir": INTEGRATION_ROOT / "EquipApiNewShop",
        "stage1": ["equip_api.py"],
        "stage2": ["migrate_to_pospro.py", "--workers", "8"],
    },
}

HEARTBEAT_INTERVAL = 5
COMMAND_POLL_INTERVAL = 10
SETTINGS_REFRESH_INTERVAL = 60

# При недоступности прод-сервера (например DNS ещё не поднят после ребута
# или интернет моргнул) — экспоненциальный backoff вместо тактового ретрая.
# Успешный ответ сбрасывает backoff обратно к нормальному интервалу.
BACKOFF_MAX = 30
# Логировать каждую неудачу спамом бессмысленно. Пишем в лог только:
#   - Первую неудачу (переход online → offline)
#   - Каждые LOG_FAILURE_EVERY_SEC при устойчивом даунтайме
#   - Восстановление (offline → online)
LOG_FAILURE_EVERY_SEC = 60

# ── Logging ─────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "worker.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("worker")
# Заглушим Werkzeug — HTTP-сервер шлёт мусор про каждый /report хит.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ── HTTP клиент к прод-серверу ──────────────────────────────────────


class PosProClient:
    def __init__(self):
        self.base = f"{API_URL}/api/admin/integrations/internal"
        self.headers = {"X-Integration-Key": INTEGRATION_KEY}
        self.session = requests.Session()

    def _url(self, type_: str, path: str) -> str:
        return f"{self.base}/{type_}/{path.lstrip('/')}"

    def heartbeat(self, type_: str) -> bool:
        # Ловим ВСЕ исключения (не только RequestException) — иначе тред падает
        # молча на неожиданных вещах типа ConnectionAbortedError / OSError / SSL.
        try:
            r = self.session.post(self._url(type_, "heartbeat"), headers=self.headers, timeout=10)
            return r.ok
        except Exception:
            return False

    def get_settings(self, type_: str) -> dict | None:
        try:
            r = self.session.get(self._url(type_, "settings"), headers=self.headers, timeout=10)
            if r.ok:
                return r.json()
        except Exception:
            pass
        return None

    def get_pending_command(self, type_: str) -> dict | None:
        try:
            r = self.session.get(self._url(type_, "pending-command"), headers=self.headers, timeout=10)
            if r.ok:
                return r.json().get("command")
        except Exception:
            pass
        return None

    def create_run(self, type_: str, trigger: str, triggered_by: str | None = None) -> int | None:
        try:
            r = self.session.post(
                self._url(type_, "run"),
                headers=self.headers,
                json={"trigger": trigger, "triggered_by": triggered_by, "phase": "starting"},
                timeout=10,
            )
            if r.ok:
                return r.json().get("id")
        except requests.RequestException as e:
            log.warning("create_run %s failed: %s", type_, e)
        return None

    def update_run(self, type_: str, run_id: int, **fields) -> bool:
        body = {k: v for k, v in fields.items() if v is not None}
        if not body:
            return True
        try:
            r = self.session.post(
                self._url(type_, f"run/{run_id}"),
                headers=self.headers,
                json=body,
                timeout=10,
            )
            return r.ok
        except requests.RequestException as e:
            log.warning("update_run %s#%d failed: %s", type_, run_id, e)
            return False


client = PosProClient()


# ── State для текущих активных run'ов ────────────────────────────────

# {type_: {"run_id": int, "progress": {...}}} — обновляется runner'ом и
# читается progress endpoint'ом. Lock защищает merge разных обновлений.
active_runs: dict[str, dict] = {}
active_lock = threading.Lock()


def _empty_progress() -> dict:
    """Стартовая структура прогресса — воркер и скрипты добавляют туда данные."""
    return {
        "current_step": None,      # текущий шаг типа "fetch_products"
        "current_message": None,   # человекочитаемое сообщение
        "steps": {},               # {step_name: {status, count/done/total/success/failed}}
    }


def report_progress(type_: str, patch: dict) -> None:
    """
    Мержит частичный апдейт в active_runs[type_].progress и отправляет
    ВЕСЬ прогресс на прод. Мерж поверхностный кроме поля 'steps' — там
    сливаем по step_name чтобы не терять уже завершённые шаги.
    """
    with active_lock:
        state = active_runs.get(type_)
        if not state:
            log.debug("[%s] progress patch без active run, игнор", type_)
            return
        progress = state["progress"]

        # Верхнеуровневые поля (current_step, current_message, upload и т.п.)
        for k, v in patch.items():
            if k == "steps" and isinstance(v, dict):
                for step_name, step_data in v.items():
                    existing = progress["steps"].get(step_name, {})
                    if isinstance(existing, dict) and isinstance(step_data, dict):
                        merged = {**existing, **step_data}
                        progress["steps"][step_name] = merged
                    else:
                        progress["steps"][step_name] = step_data
            else:
                progress[k] = v

        # Отправка на прод. Не под lock'ом чтобы не блокировать другие
        # отчёты — но копию берём под lock'ом чтобы избежать гонок.
        snapshot = json.loads(json.dumps(progress))
        run_id = state["run_id"]

    # Асинхронно шлём в прод. Ошибки не пробрасываем — прогресс best-effort.
    try:
        client.update_run(type_, run_id, progress=snapshot)
    except Exception as e:
        log.warning("[%s] отправка progress упала: %s", type_, e)


# ── Локальный HTTP-сервер для приёма отчётов от скриптов миграции ────

progress_app = Flask("progress_server")


@progress_app.post("/report")
def http_report():
    """
    Скрипты BIO/Equip шлют сюда JSON:
      {
        "type": "bio",           // обязательно
        "current_step": "fetch_products",
        "current_message": "Сбор товаров...",
        "steps": {
            "fetch_products": {"status": "running", "done": 300, "total": 1566}
        },
        "upload": {"done": 100, "total": 1566, "success": 98, "failed": 2}
      }
    """
    data = request.get_json(silent=True) or {}
    type_ = data.pop("type", None)
    if not type_ or type_ not in INTEGRATIONS:
        return jsonify({"error": "bad_type"}), 400
    report_progress(type_, data)
    return jsonify({"ok": True}), 200


def _start_progress_server():
    """Запускает Flask в отдельном потоке — принимает POST /report от миграций."""
    def _run():
        try:
            progress_app.run(host=PROGRESS_HOST, port=PROGRESS_PORT, use_reloader=False, threaded=True)
        except Exception as e:
            log.exception("Progress HTTP server crashed: %s", e)

    threading.Thread(target=_run, daemon=True, name="progress_http").start()
    log.info("Progress HTTP server: %s", PROGRESS_URL)


# ── Runner: запуск миграций как subprocess ──────────────────────────


class MigrationRunner:
    def __init__(self, type_: str):
        self.type = type_
        self.cfg = INTEGRATIONS[type_]
        self.dir = self.cfg["dir"]
        # Текущий subprocess (bio_api / migrate_from_products_db / etc.).
        # Устанавливается перед wait, стирается после. Внешний код (poll_commands
        # cancel handler) читает это чтобы убить процесс при отмене.
        self.current_proc: subprocess.Popen | None = None
        # Флаг «оператор нажал Отменить» — устанавливается извне через
        # active_runs[type_]['cancelled'] и проверяется в блоке finally run().
        self.cancelled = False

    def _run_stage(self, run_id: int, stage_name: str, args: list[str], phase: str) -> bool:
        log.info("[%s] стадия %s: %s", self.type, stage_name, " ".join(args))
        client.update_run(self.type, run_id, phase=phase, log_excerpt=f"→ {stage_name} стартовал")

        stage_log = LOG_DIR / f"{self.type}_{stage_name}_{run_id}.log"

        # Env для скрипта: INTEGRATION_PROGRESS_URL и INTEGRATION_TYPE —
        # скрипты используют модуль progress_reporter (см. BIO/Equip репо).
        script_env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "INTEGRATION_PROGRESS_URL": PROGRESS_URL,
            "INTEGRATION_TYPE": self.type,
        }

        try:
            with open(stage_log, "w", encoding="utf-8") as logf:
                proc = subprocess.Popen(
                    [PYTHON_EXE, *args],
                    cwd=str(self.dir),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    env=script_env,
                )
                self.current_proc = proc
                rc = proc.wait()
                self.current_proc = None
        except Exception as e:
            log.exception("[%s] стадия %s упала: %s", self.type, stage_name, e)
            self.current_proc = None
            client.update_run(self.type, run_id, error=str(e), log_excerpt=str(e))
            return False

        # Если оператор нажал «Отменить» — процесс был убит .terminate(),
        # rc не будет 0, но это не «ошибка стадии», это осмысленная отмена.
        if self.cancelled:
            log.info("[%s] стадия %s прервана оператором", self.type, stage_name)
            return False

        if rc != 0:
            tail = _tail_file(stage_log, 30)
            log.error("[%s] стадия %s завершилась с кодом %d", self.type, stage_name, rc)
            client.update_run(
                self.type, run_id,
                error=f"stage {stage_name} exit code {rc}",
                log_excerpt=tail,
            )
            return False

        log.info("[%s] стадия %s ok", self.type, stage_name)
        return True

    def run(self, run_id: int) -> None:
        # Регистрируем активный run — теперь /report'ы будут мержиться сюда,
        # а внешний cancel-хендлер получит доступ к self через 'runner'.
        with active_lock:
            active_runs[self.type] = {
                "run_id": run_id,
                "progress": _empty_progress(),
                "runner": self,
            }

        try:
            report_progress(self.type, {
                "current_step": "starting",
                "current_message": "Запускаем сбор данных...",
            })

            if not self._run_stage(run_id, "stage1_fetch", self.cfg["stage1"], "fetch_products"):
                # Различаем «отменил оператор» и «упала стадия».
                if self.cancelled:
                    client.update_run(self.type, run_id, status="cancelled",
                                      log_excerpt="Отменено оператором на стадии сбора данных")
                else:
                    client.update_run(self.type, run_id, status="failed")
                return
            if not self._run_stage(run_id, "stage2_upload", self.cfg["stage2"], "upload_products"):
                if self.cancelled:
                    client.update_run(self.type, run_id, status="cancelled",
                                      log_excerpt="Отменено оператором на стадии выгрузки")
                else:
                    client.update_run(self.type, run_id, status="failed")
                return

            report_progress(self.type, {
                "current_step": "done",
                "current_message": "Выгрузка завершена",
            })
            client.update_run(self.type, run_id, status="success", phase="done",
                              log_excerpt="Обе стадии завершены успешно")
            log.info("[%s] run #%d completed", self.type, run_id)
        except Exception as e:
            log.exception("[%s] run #%d crashed: %s", self.type, run_id, e)
            client.update_run(self.type, run_id, status="failed", error=str(e))
        finally:
            with active_lock:
                active_runs.pop(self.type, None)


def _tail_file(path: Path, n: int = 30) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return ""


# ── Оркестратор ─────────────────────────────────────────────────────


class Orchestrator:
    """
    Единая FIFO-очередь выполнения интеграций. Только один run активен
    в любой момент времени — второй ждёт своей очереди.

    Триггеры (расписание + ручные команды) кладут задачу в `self.run_queue`.
    Один consumer thread `_queue_consumer_loop` берёт задачи по одной,
    запускает `MigrationRunner.run` (эта операция долгая — час-два) и
    только после её завершения берёт следующую из очереди.

    Порядок гарантированно FIFO. Дедупликация: если тот же тип уже в
    очереди или уже идёт — новый триггер игнорируется чтобы не набить
    очередь одинаковыми задачами при частом polling.
    """

    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="Asia/Almaty")
        self.scheduler.start()
        self.state = {t: {"settings_hash": None} for t in INTEGRATIONS}
        self.stop_event = threading.Event()

        # FIFO очередь запусков. Кладём tuple (type_, trigger, triggered_by).
        self.run_queue: "queue.Queue[tuple[str, str, str | None]]" = queue.Queue()
        # Что consumer сейчас выполняет (для дедупликации + логов).
        self._current_running_type: str | None = None
        # Множество типов уже стоящих в очереди — для дедупликации.
        self._queued_types: set[str] = set()
        self._queue_lock = threading.Lock()

    def _enqueue(self, type_: str, trigger: str, triggered_by: str | None) -> str:
        """
        Ставит задачу в очередь. Возвращает 'started' / 'queued' / 'duplicate'.
        """
        with self._queue_lock:
            if self._current_running_type == type_ or type_ in self._queued_types:
                log.info("[%s] %s: уже в работе или очереди, игнор", type_, trigger)
                return "duplicate"
            self._queued_types.add(type_)
            self.run_queue.put((type_, trigger, triggered_by))
            other_running = self._current_running_type
            queued_count = self.run_queue.qsize()

        if other_running and other_running != type_:
            log.info("[%s] %s: сейчас идёт %s → встал в очередь (позиция %d)",
                     type_, trigger, other_running, queued_count)
            return "queued"
        log.info("[%s] %s: добавлен в очередь (%d в очереди)", type_, trigger, queued_count)
        return "started"

    def _queue_consumer_loop(self):
        """
        Основной цикл выполнения. Блокирующе берёт задачу из очереди,
        запускает MigrationRunner, освобождается для следующей.
        """
        while not self.stop_event.is_set():
            try:
                type_, trigger, triggered_by = self.run_queue.get(timeout=1)
            except queue.Empty:
                continue

            with self._queue_lock:
                self._current_running_type = type_
                self._queued_types.discard(type_)

            try:
                run_id = client.create_run(type_, trigger, triggered_by)
                if run_id is None:
                    log.error("[%s] не удалось создать run, отмена", type_)
                else:
                    log.info("[%s] стартую run #%d (trigger=%s)", type_, run_id, trigger)
                    MigrationRunner(type_).run(run_id)
                    log.info("[%s] run #%d завершён", type_, run_id)
            except Exception as e:
                log.exception("[%s] run failed: %s", type_, e)
            finally:
                with self._queue_lock:
                    self._current_running_type = None
                self.run_queue.task_done()

    def _run_integration(self, type_: str, trigger: str, triggered_by: str | None):
        """
        Совместимость с APScheduler и внешними вызовами — просто ставит
        в очередь через _enqueue. Реальное выполнение — в consumer'е.
        """
        self._enqueue(type_, trigger, triggered_by)

    def _handle_cancel(self, type_: str) -> None:
        """
        Оператор нажал «Отменить» — прод пометил cancel-команду для этого
        типа. Тут:
          1. Ставим флаг cancelled на активный runner (проверяется после
             завершения subprocess — определяет status='cancelled' vs 'failed').
          2. Убиваем текущий subprocess (bio_api / migrate / equip_api / etc.).
             .terminate() на Windows = TerminateProcess (жёстко), скрипт не
             успеет доделать текущую итерацию — но нам это и надо.
        Если run в этот момент не запущен (например уже успел завершиться
        сам), просто пишем предупреждение — вредить нечему.
        """
        with active_lock:
            state = active_runs.get(type_)

        if not state:
            log.warning("[%s] cancel: активного run нет, игнор", type_)
            return

        runner: MigrationRunner | None = state.get("runner")
        if runner is None:
            log.warning("[%s] cancel: runner не установлен, игнор", type_)
            return

        runner.cancelled = True
        proc = runner.current_proc
        if proc is not None:
            try:
                proc.terminate()
                log.info("[%s] cancel: subprocess PID=%s убит .terminate()", type_, proc.pid)
            except Exception as e:
                log.warning("[%s] cancel: не удалось убить subprocess: %s", type_, e)
        else:
            log.info("[%s] cancel: subprocess ещё не запущен (между стадиями), флаг установлен", type_)

    def _apply_schedule(self, type_: str, settings: dict):
        job_id = f"{type_}_schedule"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        if not settings.get("enabled"):
            log.info("[%s] автозапуск выключен, job не создаётся", type_)
            return

        mode = settings.get("schedule_mode")
        data = settings.get("schedule_data") or {}
        try:
            hour, minute = map(int, (data.get("time") or "03:00").split(":"))
        except (ValueError, IndexError, AttributeError):
            log.warning("[%s] некорректное время, пропускаю", type_)
            return

        try:
            if mode == "weekly":
                days = data.get("days") or []
                if not days:
                    log.info("[%s] weekly без дней, job не создаётся", type_)
                    return
                trigger = CronTrigger(day_of_week=",".join(days), hour=hour, minute=minute, timezone="Asia/Almaty")
            elif mode == "interval":
                n_days = int(data.get("days") or 14)
                anchor = data.get("anchor")
                start_date = datetime.now()
                if anchor:
                    try:
                        start_date = datetime.strptime(anchor, "%Y-%m-%d").replace(hour=hour, minute=minute)
                    except ValueError:
                        pass
                trigger = IntervalTrigger(days=n_days, start_date=start_date, timezone="Asia/Almaty")
            else:
                log.warning("[%s] неизвестный schedule_mode: %s", type_, mode)
                return

            self.scheduler.add_job(
                self._run_integration, trigger=trigger, id=job_id,
                args=[type_, "scheduled", None], replace_existing=True,
            )
            log.info("[%s] расписание применено: %s %s", type_, mode, data)
        except Exception as e:
            log.exception("[%s] ошибка применения расписания: %s", type_, e)

    def _sleep_with_backoff(self, type_: str, loop_name: str, base_interval: int,
                            success: bool, state: dict) -> None:
        """
        Единая логика ожидания следующего тика для всех poll-циклов.
        Если запрос удачный — спим base_interval и сбрасываем backoff.
        Если ошибка — экспоненциальный backoff до BACKOFF_MAX, логируем
        только при переходе состояния и раз в LOG_FAILURE_EVERY_SEC.
        """
        now = time.time()
        if success:
            if state.get("was_failing"):
                downtime = now - state.get("first_fail_at", now)
                log.info("[%s] %s: связь восстановлена (даунтайм %.0f сек)", type_, loop_name, downtime)
            state["was_failing"] = False
            state["last_log_at"] = 0
            state["first_fail_at"] = 0
            state["backoff"] = base_interval
            interval = base_interval
        else:
            if not state.get("was_failing"):
                log.warning("[%s] %s: связь с сервером потеряна, начинаю retry", type_, loop_name)
                state["was_failing"] = True
                state["first_fail_at"] = now
                state["last_log_at"] = now
                state["backoff"] = base_interval
            elif now - state.get("last_log_at", 0) > LOG_FAILURE_EVERY_SEC:
                downtime = now - state.get("first_fail_at", now)
                log.warning("[%s] %s: всё ещё нет связи (%.0f сек)", type_, loop_name, downtime)
                state["last_log_at"] = now
            # Экспоненциально: 5 → 10 → 20 → 30 (capped BACKOFF_MAX)
            state["backoff"] = min(state.get("backoff", base_interval) * 2, BACKOFF_MAX)
            interval = state["backoff"]

        self.stop_event.wait(interval)

    def _safe_loop(self, target, type_: str, name: str):
        """
        Обёртка над poll-циклом: если тред умер по uncaught exception —
        логирует stacktrace и рестартит через 5 сек. Без этой защиты
        падение одного тика убивало весь heartbeat/settings/commands loop
        молча, статус в UI застывал а причины было не найти.
        """
        while not self.stop_event.is_set():
            try:
                target(type_)
                return  # чистый выход (stop_event set)
            except Exception as e:
                log.exception("[%s] loop %s CRASHED, рестарт через 5 сек: %s", type_, name, e)
                self.stop_event.wait(5)

    def _safe_loop_no_type(self, target, name: str):
        """То же что _safe_loop, но для функций без type_ (например consumer)."""
        while not self.stop_event.is_set():
            try:
                target()
                return
            except Exception as e:
                log.exception("loop %s CRASHED, рестарт через 5 сек: %s", name, e)
                self.stop_event.wait(5)

    def _poll_settings_loop(self, type_: str):
        state = {"was_failing": False, "last_log_at": 0, "first_fail_at": 0, "backoff": SETTINGS_REFRESH_INTERVAL}
        while not self.stop_event.is_set():
            settings = client.get_settings(type_)
            if settings:
                sig = f"{settings.get('enabled')}|{settings.get('schedule_mode')}|{settings.get('schedule_data')}"
                if sig != self.state[type_]["settings_hash"]:
                    self.state[type_]["settings_hash"] = sig
                    self._apply_schedule(type_, settings)
            self._sleep_with_backoff(type_, "settings", SETTINGS_REFRESH_INTERVAL, settings is not None, state)

    def _poll_commands_loop(self, type_: str):
        state = {"was_failing": False, "last_log_at": 0, "first_fail_at": 0, "backoff": COMMAND_POLL_INTERVAL}
        while not self.stop_event.is_set():
            success = True
            try:
                r = client.session.get(
                    client._url(type_, "pending-command"),
                    headers=client.headers, timeout=10,
                )
                if r.ok:
                    cmd = r.json().get("command")
                    if cmd:
                        cmd_name = cmd.get("command")
                        if cmd_name == "run_now":
                            log.info("[%s] получена команда run_now от %s", type_, cmd.get("created_by"))
                            self._enqueue(type_, "manual", cmd.get("created_by"))
                        elif cmd_name == "cancel":
                            log.info("[%s] получена команда cancel от %s", type_, cmd.get("created_by"))
                            self._handle_cancel(type_)
                else:
                    success = False
            except Exception:
                success = False
            self._sleep_with_backoff(type_, "commands", COMMAND_POLL_INTERVAL, success, state)

    def _heartbeat_loop(self, type_: str):
        state = {"was_failing": False, "last_log_at": 0, "first_fail_at": 0, "backoff": HEARTBEAT_INTERVAL}
        while not self.stop_event.is_set():
            ok = client.heartbeat(type_)
            self._sleep_with_backoff(type_, "heartbeat", HEARTBEAT_INTERVAL, ok, state)

    def start(self):
        log.info("Worker starting. API=%s, integrations=%s", API_URL, list(INTEGRATIONS.keys()))
        if not INTEGRATION_KEY:
            log.error("INTEGRATION_KEY не задан в .env — все запросы к серверу будут отвергнуты")
            return

        _start_progress_server()

        # Единый consumer очереди — только один run одновременно (BIO и
        # Equip идут строго последовательно, не могут пересекаться).
        threading.Thread(
            target=self._safe_loop_no_type, args=[self._queue_consumer_loop, "queue_consumer"],
            daemon=True, name="run_queue_consumer",
        ).start()

        for type_ in INTEGRATIONS:
            for target, loop_name in (
                (self._heartbeat_loop, "heartbeat"),
                (self._poll_settings_loop, "settings"),
                (self._poll_commands_loop, "commands"),
            ):
                threading.Thread(
                    target=self._safe_loop, args=[target, type_, loop_name],
                    daemon=True, name=f"{loop_name}_{type_}",
                ).start()

        def _stop(*_):
            log.info("Received stop signal, shutting down...")
            self.stop_event.set()
            self.scheduler.shutdown(wait=False)
            sys.exit(0)

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, _stop)

        while not self.stop_event.is_set():
            time.sleep(1)


if __name__ == "__main__":
    Orchestrator().start()
