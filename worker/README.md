# Локальный воркер интеграций (BIO/Equip)

Живёт на резервном ПК (`192.168.1.99`, `R:\integration\worker\`). Windows Service `PosProIntegrationWorker` под LocalSystem через nssm — headless subprocess-запуск скриптов миграции (`bio_api.py`, `migrate_from_products_db.py`, аналогично Equip). APScheduler по расписанию, поллинг команд, локальный HTTP-сервер на 9876 для прогресс-репортов.

## Файлы
- `main.py` — сам воркер
- `.env.example` — шаблон конфига (реальный `.env` только на локалке, не в git)

## Как обновить код на локалке
```
scp worker/main.py reserve:/R:/integration/worker/main.py
ssh reserve "nssm restart PosProIntegrationWorker"
```

## Скрипты BIO/Equip
Живут в отдельных git-репо, клонированы на локалку через SSH deploy keys:
- BIO — https://github.com/BLINK-sys/POSPRO_BIO_WORKER (`R:\integration\BioApiNewShop\`)
- Equip — https://github.com/BLINK-sys/POSPRO_EQUIP_WORKER (`R:\integration\EquipApiNewShop\`)

Обновление:
```
ssh reserve "cd /D R:\integration\BioApiNewShop & git pull"
ssh reserve "cd /D R:\integration\EquipApiNewShop & git pull"
```

## Соседний воркер: 2GIS collector

Отдельный процесс, отдельный git-репо, отдельный Task Scheduler task. Живёт в `R:\integration\collector\worker\collector_main.py`, обновляется через `git pull` в `R:\integration\collector\` (репо POSPRO_2GIS_COLLECTOR). См. соответствующий проект в обсидиан-волте магазина.

Раньше `collector_main.py` жил в этой же папке `pospro_new_server/worker/`, но это триггерило редеплой Render на каждую правку воркера — вынесен в свой репо 2026-08-03.
