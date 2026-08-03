@echo off
REM Wrapper для collector-воркера: рестарт при падении.
REM Task Scheduler запускает этот bat при логоне admin.
REM Bat в бесконечном цикле держит python-процесс живым — если процесс
REM упал (уронили из Task Manager, антибот 2GIS убил, unhandled exception,
REM Windows Update — что угодно), bat подождёт 5 секунд и стартанёт заново.
REM
REM Логи самого питона остаются в logs\collector_worker.log,
REM здесь только маркеры start/exit в logs\wrapper.log.

SET WORKER_DIR=R:\integration\collector\worker
SET VENV_PY=R:\integration\collector\.venv\Scripts\pythonw.exe

cd /d %WORKER_DIR%

:loop
echo [%date% %time%] Starting collector_main.py >> logs\wrapper.log
%VENV_PY% %WORKER_DIR%\collector_main.py
echo [%date% %time%] Process exited (code %ERRORLEVEL%), restart in 5s >> logs\wrapper.log
timeout /t 5 /nobreak >nul
goto loop
