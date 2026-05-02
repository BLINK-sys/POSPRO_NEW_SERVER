"""
Скачивание внешних картинок в локальное хранилище.

Используется в PUT /categories/<id> и PUT /meta/brands/<id>: когда туда
прилетает image_url с http(s) (внешняя ссылка), мы качаем файл и кладём
его под /uploads/<subfolder>/. В image_url у Сategory/Brand сохраняется
уже локальный путь — внешние ссылки не сохраняются (иначе картинка может
исчезнуть, когда стухнет URL).
"""
import os
import uuid
from urllib.parse import unquote, urlparse

import requests
from flask import current_app
from werkzeug.utils import secure_filename


_FETCH_TIMEOUT = 30
_MAX_BYTES = 10 * 1024 * 1024  # 10 МБ
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
}
_EXT_TO_MIME = {v: k for k, v in _MIME_TO_EXT.items()} | {"jpeg": "image/jpeg"}


def is_external_image_url(url):
    """True если url — http(s) и НЕ указывает на наш /uploads/."""
    if not url or not isinstance(url, str):
        return False
    s = url.strip()
    if not s:
        return False
    if s.startswith("/uploads/"):
        return False
    return s.startswith("http://") or s.startswith("https://")


def download_to_uploads(image_url, subfolder):
    """
    Скачивает картинку с image_url в UPLOAD_FOLDER/<subfolder>/.
    `subfolder` — например 'categories/15' или 'brands/3'.

    Возвращает (local_url, error). При успехе error=None и
    local_url='/uploads/<subfolder>/<filename>'. При ошибке local_url=None
    и error содержит читаемую причину (для логов / API ответа).
    """
    if not is_external_image_url(image_url):
        return None, "URL не http(s) или уже локальный"

    parsed = urlparse(image_url)
    if not parsed.netloc:
        return None, "URL без домена"

    # Скачиваем
    try:
        resp = requests.get(
            image_url,
            headers={"User-Agent": "Mozilla/5.0 PosProBot/1.0"},
            timeout=_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
    except requests.exceptions.RequestException as e:
        return None, f"Не удалось скачать: {e}"

    if resp.status_code != 200:
        return None, f"Источник вернул HTTP {resp.status_code}"

    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    # Yandex Cloud для части файлов отдаёт application/octet-stream — доверяем
    # расширению из URL в этом случае.
    url_ext = (os.path.splitext(parsed.path)[1] or "").lower().lstrip(".")
    if not content_type.startswith("image/"):
        guessed = _EXT_TO_MIME.get(url_ext)
        if guessed:
            content_type = guessed
        else:
            return None, f"URL не является изображением (Content-Type: {content_type or 'none'})"

    # Читаем с лимитом
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=64_000):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_BYTES:
            return None, f"Файл слишком большой (>{_MAX_BYTES // (1024 * 1024)} МБ)"
    blob = b"".join(chunks)

    if not blob:
        return None, "Пустой ответ"

    # Определяем имя файла: предпочитаем basename из URL, иначе uuid + расширение
    url_filename = secure_filename(os.path.basename(unquote(parsed.path)) or "")
    has_ext = "." in url_filename and url_filename.rsplit(".", 1)[1].lower() in _MIME_TO_EXT.values()
    if not has_ext:
        ext = _MIME_TO_EXT.get(content_type, url_ext or "jpg")
        base = url_filename.rsplit(".", 1)[0] if "." in url_filename else url_filename
        if not base:
            base = uuid.uuid4().hex[:12]
        url_filename = f"{base}.{ext}"

    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)

    filepath = os.path.join(folder, url_filename)
    if os.path.exists(filepath):
        stem, ext = os.path.splitext(url_filename)
        url_filename = f"{stem}-{uuid.uuid4().hex[:6]}{ext}"
        filepath = os.path.join(folder, url_filename)

    try:
        with open(filepath, "wb") as f:
            f.write(blob)
    except Exception as e:
        return None, f"Не удалось сохранить файл: {e}"

    return f"/uploads/{subfolder}/{url_filename}", None


def remove_local_upload(local_url):
    """
    Удаляет файл по локальному URL вида '/uploads/...'. Тихо игнорирует
    ошибки (отсутствующие файлы, права и т.п.) — логируем в stderr.
    """
    if not local_url or not local_url.startswith("/uploads/"):
        return
    rel_path = local_url[len("/uploads/"):]
    full = os.path.join(current_app.config["UPLOAD_FOLDER"], rel_path)
    try:
        if os.path.exists(full):
            os.remove(full)
    except Exception as e:
        # Не критично, файл может остаться — но запись в БД мы уже перепишем
        print(f"[external_image] Не удалось удалить {full}: {e}")
