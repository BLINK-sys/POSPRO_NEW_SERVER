import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
timeout = 300

# Render Standard (2 GB, 1 CPU): 4 worker'а × 4 потока = 16 параллельных
# запросов. На Starter было 2x4=8, упирались в backend под нагрузкой
# параллельной миграции 8-поточного клиента. С 4 worker'ами хватает
# памяти и для миграции, и для обычного трафика без задержек.
worker_class = "gthread"
workers = 4
threads = 4
