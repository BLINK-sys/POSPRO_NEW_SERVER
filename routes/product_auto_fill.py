"""
AI-driven product page parser.

POST /api/admin/products/auto-fill {url}
  → fetches the source page, hands the cleaned HTML to Claude with a
    structured-output tool, and returns extracted product data:
    name, description (translated to Russian), image_urls (up to 10),
    characteristics ([{key, value, unit}]).

Used by the admin product create form when the operator pastes a URL
to a competitor / supplier product page.

Access is gated through ai_consultant_access.allowed_product_import_user_ids.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests
from flask import Blueprint, request, jsonify

from routes.ai_consultant_access import _resolve_viewer, _has_product_import_access
from extensions import db
from models.ai_logs import AIImportLog, IMPORT_STATUS_ERROR, IMPORT_STATUS_IMPORTED
from models.ai_consultant_access import AIConsultantAccess

product_auto_fill_bp = Blueprint('product_auto_fill', __name__)

ANTHROPIC_API_KEY = (os.getenv('ANTHROPIC_API_KEY') or '').strip()
MODEL_ID = 'claude-haiku-4-5'

# Page-fetch limits — keep the operator from accidentally pointing the
# server at a 50MB binary.
MAX_HTML_BYTES = 1_500_000  # ~1.5MB raw HTML; we strip/trim before sending to Claude
HTML_FETCH_TIMEOUT = 15
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# Headers a real Chrome on Windows would send. Many WAFs flag requests
# that are missing the secondary fingerprint headers (sec-ch-ua,
# accept-language, etc.) — sending them dramatically reduces 403 rates
# from sites with default-on anti-bot rules.
_BROWSER_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

# After cleaning we cap to this many characters so the Anthropic input
# token bill stays bounded (~25-30K tokens at most).
MAX_CLAUDE_INPUT_CHARS = 100_000

MAX_IMAGE_URLS = 10


SYSTEM_PROMPT = """Ты помогаешь админу магазина оборудования заполнить карточку товара.
Тебе дают HTML страницы товара с любого сайта-донора. Твоя задача — извлечь:

1. **name** — название товара. НЕ переводить на русский, оставлять оригинал
   как есть на странице.
2. **description** — текстовое описание товара. ОБЯЗАТЕЛЬНО на русском —
   если оригинал на английском/китайском/любом другом языке, переведи. Без
   HTML-тегов, чистый текст. Не выдумывай характеристики которых нет.
3. **image_urls** — до 10 абсолютных URL РЕАЛЬНЫХ ФОТО товара. Исключай:
   логотипы магазина, баннеры, рекламу, иконки соцсетей, аватарки отзывов,
   декоративные изображения. Если у товара несколько ракурсов — бери все.
   Только товарные фотографии. Предпочитай высокое разрешение (если на
   странице есть и thumbnail и полная версия — бери полную).
4. **characteristics** — массив объектов {key, value, unit}. Ключи и
   значения на РУССКОМ (переводи если на другом языке). Единица измерения
   отдельным полем "unit" (например "л", "кВт", "мм", "°C") — если её нет
   в исходных данных, оставь пустую строку. Если в одной строке указано
   несколько значений (диапазон), бери как есть строкой в value.

Если каких-то данных на странице нет — верни пустую строку или пустой
массив, не выдумывай."""


def _clean_html(html: str) -> str:
    """Strip noise and trim to a Claude-friendly size."""
    # Remove scripts/styles/svg/iframe/noscript with their content
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<style\b[^>]*>.*?</style>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<noscript\b[^>]*>.*?</noscript>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<svg\b[^>]*>.*?</svg>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<iframe\b[^>]*>.*?</iframe>', '', html, flags=re.IGNORECASE | re.DOTALL)
    # Strip HTML comments (often huge with templating frameworks)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # Collapse whitespace runs
    html = re.sub(r'\s+', ' ', html)
    return html[:MAX_CLAUDE_INPUT_CHARS]


def _validate_url(url: str) -> tuple[bool, str]:
    """Return (ok, error_message). Accept http/https only."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, 'Некорректный URL'
    if parsed.scheme not in ('http', 'https'):
        return False, 'URL должен начинаться с http:// или https://'
    if not parsed.netloc:
        return False, 'URL должен содержать домен'
    return True, ''


def _fetch_html(url: str) -> tuple[str | None, str | None]:
    """Returns (html, error). On success error is None."""
    # Send a Referer that matches the page's own host — some anti-bot
    # rules treat "no referer" as suspicious. Using the page's own origin
    # mimics the user clicking from a search result on the same site.
    parsed = urlparse(url)
    headers = dict(_BROWSER_HEADERS)
    if parsed.scheme and parsed.netloc:
        headers['Referer'] = f'{parsed.scheme}://{parsed.netloc}/'

    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=HTML_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
    except requests.exceptions.Timeout:
        return None, 'Сайт-донор не ответил вовремя (таймаут 15с)'
    except requests.exceptions.RequestException as e:
        return None, f'Ошибка загрузки страницы: {e}'

    if resp.status_code != 200:
        # Provide a more useful hint for the common 403 case
        if resp.status_code == 403:
            return None, (
                'Сайт-донор отклонил запрос (HTTP 403). У него стоит '
                'защита от ботов или он рендерит контент через JavaScript. '
                'Попробуйте другой источник.'
            )
        return None, f'Сайт-донор вернул HTTP {resp.status_code}'

    content_type = (resp.headers.get('Content-Type') or '').lower()
    if 'html' not in content_type and 'xml' not in content_type:
        return None, f'URL не является HTML-страницей (Content-Type: {content_type})'

    # Read with size cap to avoid downloading huge files
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=64_000):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_HTML_BYTES:
            break
    raw = b''.join(chunks)
    # Best-effort decode
    encoding = resp.encoding or 'utf-8'
    try:
        return raw.decode(encoding, errors='replace'), None
    except LookupError:
        return raw.decode('utf-8', errors='replace'), None


def _call_claude(html: str, source_url: str) -> tuple[dict | None, str | None]:
    """Call Anthropic Claude with structured tool-use output."""
    if not ANTHROPIC_API_KEY:
        return None, 'ANTHROPIC_API_KEY не настроен на сервере'

    try:
        import anthropic
    except ImportError:
        return None, 'Библиотека anthropic не установлена'

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    tool_schema = {
        'name': 'submit_product_data',
        'description': 'Submit extracted product data from the page. Call this once with all extracted fields.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Original product name as on the page (do NOT translate)'},
                'description': {'type': 'string', 'description': 'Plain-text product description in Russian'},
                'image_urls': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': f'Up to {MAX_IMAGE_URLS} absolute URLs of actual product photos',
                },
                'characteristics': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'key': {'type': 'string'},
                            'value': {'type': 'string'},
                            'unit': {'type': 'string'},
                        },
                        'required': ['key', 'value'],
                    },
                    'description': 'Product specs/characteristics, keys and values in Russian',
                },
            },
            'required': ['name', 'description', 'image_urls', 'characteristics'],
        },
    }

    user_content = (
        f'Источник: {source_url}\n\n'
        f'HTML страницы (отчищен от script/style):\n\n'
        f'{html}'
    )

    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=[tool_schema],
            tool_choice={'type': 'tool', 'name': 'submit_product_data'},
            messages=[{'role': 'user', 'content': user_content}],
            timeout=60.0,
        )
    except Exception as e:
        return None, f'Ошибка вызова Claude: {e}'

    # Extract the tool_use block
    for block in response.content:
        if getattr(block, 'type', None) == 'tool_use' and getattr(block, 'name', None) == 'submit_product_data':
            return dict(block.input), None

    return None, 'Claude не вызвал submit_product_data'


def _normalize_extracted(data: dict, source_url: str) -> dict:
    """Defensive cleanup of Claude's output."""
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()

    # Image URLs: keep absolute, drop data:, dedupe, cap.
    raw_urls = data.get('image_urls') or []
    seen = set()
    image_urls: list[str] = []
    for u in raw_urls:
        if not isinstance(u, str):
            continue
        u = u.strip()
        if not u or u.lower().startswith('data:'):
            continue
        # Resolve protocol-relative URLs
        if u.startswith('//'):
            scheme = urlparse(source_url).scheme or 'https'
            u = f'{scheme}:{u}'
        # Skip relative URLs — model should return absolute, but defend
        if not (u.startswith('http://') or u.startswith('https://')):
            continue
        if u in seen:
            continue
        seen.add(u)
        image_urls.append(u)
        if len(image_urls) >= MAX_IMAGE_URLS:
            break

    # Characteristics: keep only items with non-empty key+value
    raw_chars = data.get('characteristics') or []
    characteristics: list[dict] = []
    for c in raw_chars:
        if not isinstance(c, dict):
            continue
        key = (c.get('key') or '').strip()
        value = (c.get('value') or '').strip()
        unit = (c.get('unit') or '').strip()
        if not key or not value:
            continue
        characteristics.append({'key': key, 'value': value, 'unit': unit})

    return {
        'name': name,
        'description': description,
        'image_urls': image_urls,
        'characteristics': characteristics,
    }


def _log_import_attempt(viewer, source_url, status, imported_data=None, error_message=None):
    """
    Пишет одну строку в ai_import_logs. Тихо подавляет ошибки записи —
    логирование не должно ломать основной флоу.
    Возвращает id лога или None.
    """
    try:
        log = AIImportLog(
            user_id=viewer.get('user_id'),
            user_email=viewer.get('email') or 'unknown',
            user_role=viewer.get('kind') or 'system',
            source_url=source_url,
            status=status,
            imported_data=imported_data,
            error_message=error_message,
        )
        db.session.add(log)
        db.session.commit()
        return log.id
    except Exception as e:
        db.session.rollback()
        # Логируем в stderr, но в ответе клиенту ничего не теряем
        print(f"[ai-import-log] failed to record: {type(e).__name__}: {e}")
        return None


def _summarize_for_log(data: dict) -> dict:
    """Компактное представление вытащенных данных для лога — без полного
    HTML-описания и без массивов URL'ов чтобы не раздувать БД."""
    return {
        'name': (data.get('name') or '')[:255],
        'description_length': len(data.get('description') or ''),
        'characteristics_count': len(data.get('characteristics') or []),
        'images_count': len(data.get('image_urls') or []),
    }


@product_auto_fill_bp.route('/admin/products/auto-fill', methods=['POST'])
def auto_fill():
    # Access check — same gate as the UI button
    viewer = _resolve_viewer()
    settings = AIConsultantAccess.get_or_create()
    if not _has_product_import_access(viewer, settings):
        return jsonify({'error': 'Доступ к импорту товаров не выдан'}), 403

    body = request.get_json(silent=True) or {}
    url = (body.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'Поле url обязательно'}), 400

    ok, err = _validate_url(url)
    if not ok:
        _log_import_attempt(viewer, url, IMPORT_STATUS_ERROR, error_message=err)
        return jsonify({'error': err}), 400

    html, err = _fetch_html(url)
    if err:
        _log_import_attempt(viewer, url, IMPORT_STATUS_ERROR, error_message=err)
        return jsonify({'error': err}), 400

    cleaned = _clean_html(html or '')
    if len(cleaned) < 100:
        msg = 'Страница пустая или не содержит распознаваемого HTML'
        _log_import_attempt(viewer, url, IMPORT_STATUS_ERROR, error_message=msg)
        return jsonify({'error': msg}), 400

    extracted, err = _call_claude(cleaned, url)
    if err:
        _log_import_attempt(viewer, url, IMPORT_STATUS_ERROR, error_message=err)
        return jsonify({'error': err}), 502

    data = _normalize_extracted(extracted or {}, url)
    log_id = _log_import_attempt(
        viewer, url, IMPORT_STATUS_IMPORTED,
        imported_data=_summarize_for_log(data),
    )
    # import_log_id передаётся клиенту, чтобы он PATCH-ом обновил его на
    # IMPORT_STATUS_SAVED после реального сохранения товара.
    return jsonify({'success': True, 'data': data, 'import_log_id': log_id}), 200
