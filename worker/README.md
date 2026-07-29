# Локальные воркеры

На резервном ПК живут **два независимых воркера** — у каждого своя роль и своя изоляция.

## `main.py` — воркер интеграций (BIO/Equip)
Windows Service `PosProIntegrationWorker` (nssm, под LocalSystem). APScheduler по расписанию, поллинг команд, subprocess-запуск скриптов миграции (`bio_api.py`, `migrate_from_products_db.py`, аналогично Equip), локальный HTTP-сервер на 9876 для прогресс-репортов.

## `collector_main.py` — воркер сервиса сбора 2GIS
Task Scheduler «At logon» под юзером **Алина** (НЕ Windows Service — `gis2_collector.collect()` использует `headless=False` Chrome, для которого нужна живая desktop-сессия). Тянет задачи с прода порционно (`/api/admin/collector/internal/next-task`), гоняет `collect()` в одном consumer-треде (второй Chrome не поднимается на этом железе), после каждой пары multipart-заливает .xlsx на прод в `/disk/uploads/collector/`.

## Файлы
- `main.py` — воркер BIO/Equip
- `collector_main.py` — воркер 2GIS-сбора
- `.env.example` — шаблон конфига (реальный `.env` только на локалке, не в git)

## Как обновить код на локалке

**BIO/Equip воркер:**
```
scp worker/main.py reserve:/R:/integration/worker/main.py
ssh reserve "nssm restart PosProIntegrationWorker"
```

**2GIS collector воркер:**
```
scp worker/collector_main.py reserve:/R:/integration/collector/worker/collector_main.py
# Restart делает Task Scheduler или юзер вручную через админку планировщика
# (или скрипт stop/start под юзером Алина)
```

## Обновление скриптов BIO/Equip
Через git на локалке:
```
ssh reserve "cd /D R:\integration\BioApiNewShop & git pull"
ssh reserve "cd /D R:\integration\EquipApiNewShop & git pull"
```

## Repos
- BIO — https://github.com/BLINK-sys/POSPRO_BIO_WORKER
- Equip — https://github.com/BLINK-sys/POSPRO_EQUIP_WORKER

Оба клонированы на локалку через SSH deploy keys (read-only) в `R:\integration\`.
