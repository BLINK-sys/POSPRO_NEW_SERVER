import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
timeout = 300

# Render Standard (2 GB, 1 CPU): 4 worker'а × 32 потока = 128 параллельных
# запросов. 2026-10-21: подняли с 16 до 128 потому что SSE-стримы
# /api/admin/chat/stream держат gthread на весь срок подписки
# (минутами-часами), а при 16 слотах 16 активных менеджеров → все
# слоты заняты, обычные HTTP-запросы висят в очереди → клиент видит
# timeout / "Не удалось загрузить данные". На коротких REST-запросах
# 128 threads не грузят CPU (I/O-bound), память на один thread ~5-10 МБ
# → 128 × 10 МБ ≈ 1.3 ГБ — укладывается в 2 ГБ Standard'а.
worker_class = "gthread"
workers = 4
threads = 32
