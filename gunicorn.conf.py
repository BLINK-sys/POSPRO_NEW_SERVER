import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
timeout = 300

# Render Starter (512 MB): 2 worker'а × 4 потока = 8 параллельных запросов.
# Threads (gthread) делят память внутри одного worker'а — дешевле, чем
# наращивать workers. Раньше был `workers = 1`, из-за этого тяжёлые запросы
# (импорт каталога с скачкой картинок) полностью блокировали сайт для
# обычных пользователей.
worker_class = "gthread"
workers = 2
threads = 4
