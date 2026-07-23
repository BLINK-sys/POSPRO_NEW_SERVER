# Локальный воркер интеграций (BIO/Equip)

Не крутится на Render. Живёт на резервном ПК (`192.168.1.99`, Windows Service `PosProIntegrationWorker`, устанавливается через nssm).

## Файлы
- `main.py` — сам воркер (APScheduler + heartbeat + subprocess-запуск миграций + HTTP-сервер для progress)
- `.env.example` — шаблон конфига (реальный `.env` только на локалке, не в git)

## Как обновить код на локалке
```
ssh reserve "\"R:\integration\tools\nssm.exe\" stop PosProIntegrationWorker"
scp worker/main.py reserve:./worker_main.py
ssh reserve "move /Y worker_main.py R:\integration\worker\main.py & \"R:\integration\tools\nssm.exe\" start PosProIntegrationWorker"
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
