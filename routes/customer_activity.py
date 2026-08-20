"""
Трекинг активности покупателей (не admin/system) + админский отчёт.

Публичный эндпоинт (JWT optional):
  POST /api/track-customer-activity

Админские (JWT required, role admin/system):
  GET  /api/admin/customer-activity           — список с фильтром/пагинацией
  GET  /api/admin/customer-activity/summary   — топ-N по типу за период
"""

import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, jwt_required
from sqlalchemy import desc, func

from extensions import db
from models.customer_activity import CustomerActivity
from routes.dashboard import parse_date_range


customer_activity_bp = Blueprint('customer_activity', __name__)


_BOT_KEYWORDS = (
    'bot', 'crawl', 'spider', 'slurp', 'scraper', 'fetch',
    'curl', 'wget', 'python-requests', 'httpx', 'aiohttp',
    'googlebot', 'bingbot', 'yandexbot', 'baiduspider',
    'duckduckbot', 'facebookexternalhit', 'twitterbot',
    'linkedinbot', 'whatsapp', 'telegrambot', 'discordbot',
    'semrushbot', 'ahrefsbot', 'dotbot', 'mj12bot',
    'petalbot', 'bytespider', 'gptbot', 'claudebot',
    'headlesschrome', 'phantomjs', 'selenium', 'puppeteer',
    'lighthouse', 'pagespeed', 'pingdom', 'uptimerobot',
    'monitoring', 'checker', 'scanner', 'probe',
)


def _client_ip() -> str:
    ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    if not ip:
        ip = request.headers.get('X-Real-Ip', request.remote_addr or 'unknown')
    return ip or 'unknown'


def _is_bot(user_agent: str) -> bool:
    if not user_agent:
        return True
    ua_lower = user_agent.lower()
    return any(kw in ua_lower for kw in _BOT_KEYWORDS)


def _current_role_and_uid():
    """Достаём role/user_id из JWT (optional). Возвращаем (role, uid|None)."""
    try:
        verify_jwt_in_request(optional=True)
        claims = get_jwt() or {}
        role = claims.get('role') or 'guest'
        # sub у нас = str id, но иногда числом. Не критично — используем как есть.
        uid_raw = claims.get('sub')
        try:
            uid = int(uid_raw) if uid_raw is not None else None
        except (TypeError, ValueError):
            uid = None
        return role, uid
    except Exception:
        return 'guest', None


@customer_activity_bp.route('/track-customer-activity', methods=['POST'])
def track_customer_activity():
    data = request.get_json(silent=True) or {}
    event_type = (data.get('event_type') or '').strip()
    if event_type not in ('search', 'category_view', 'brand_view'):
        return jsonify({'error': 'invalid event_type'}), 400

    role, user_id = _current_role_and_uid()
    # Админов и system-юзеров не считаем.
    if role in ('admin', 'system'):
        return jsonify({'success': True, 'skipped': 'admin'}), 200

    user_agent = data.get('user_agent') or request.headers.get('User-Agent', '')
    if _is_bot(user_agent):
        return jsonify({'success': True, 'skipped': 'bot'}), 200

    ip = _client_ip()

    # Дедуп для category_view / brand_view: одно и то же (ip, entity_id)
    # в течение 5 минут = один просмотр. search — не дедуплим (каждая
    # попытка отдельная запись).
    now = datetime.datetime.now()
    dedup_min = 5

    if event_type == 'category_view':
        cat_id = data.get('category_id')
        if not cat_id:
            return jsonify({'error': 'category_id required'}), 400
        recent = CustomerActivity.query.filter(
            CustomerActivity.event_type == 'category_view',
            CustomerActivity.ip_address == ip,
            CustomerActivity.category_id == cat_id,
            CustomerActivity.created_at >= now - datetime.timedelta(minutes=dedup_min),
        ).first()
        if recent:
            return jsonify({'success': True, 'deduplicated': True}), 200

        ev = CustomerActivity(
            event_type='category_view',
            user_id=user_id,
            ip_address=ip,
            user_agent=user_agent,
            category_id=cat_id,
            category_name=(data.get('category_name') or '')[:255] or None,
            category_slug=(data.get('category_slug') or '')[:255] or None,
        )

    elif event_type == 'brand_view':
        brand_id = data.get('brand_id')
        if not brand_id:
            return jsonify({'error': 'brand_id required'}), 400
        recent = CustomerActivity.query.filter(
            CustomerActivity.event_type == 'brand_view',
            CustomerActivity.ip_address == ip,
            CustomerActivity.brand_id == brand_id,
            CustomerActivity.created_at >= now - datetime.timedelta(minutes=dedup_min),
        ).first()
        if recent:
            return jsonify({'success': True, 'deduplicated': True}), 200

        ev = CustomerActivity(
            event_type='brand_view',
            user_id=user_id,
            ip_address=ip,
            user_agent=user_agent,
            brand_id=brand_id,
            brand_name=(data.get('brand_name') or '')[:255] or None,
        )

    else:  # search
        q = (data.get('query') or '').strip()
        if not q:
            return jsonify({'error': 'query required'}), 400
        try:
            results_count = int(data.get('results_count') or 0)
        except (TypeError, ValueError):
            results_count = 0
        ev = CustomerActivity(
            event_type='search',
            user_id=user_id,
            ip_address=ip,
            user_agent=user_agent,
            search_query=q[:500],
            results_count=results_count,
        )

    db.session.add(ev)
    db.session.commit()
    return jsonify({'success': True}), 200


def _admin_guard():
    claims = get_jwt() or {}
    if claims.get('role') not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


@customer_activity_bp.route('/admin/customer-activity', methods=['GET'])
@jwt_required()
def list_customer_activity():
    denied = _admin_guard()
    if denied:
        return denied

    date_from, date_to = parse_date_range(request.args)
    event_type = request.args.get('type', 'all')
    search = (request.args.get('search') or '').strip()
    page = max(request.args.get('page', default=1, type=int) or 1, 1)
    per_page = max(1, min(request.args.get('per_page', default=50, type=int) or 50, 200))

    q = CustomerActivity.query.filter(
        CustomerActivity.created_at >= date_from,
        CustomerActivity.created_at <= date_to,
    )
    if event_type != 'all':
        q = q.filter(CustomerActivity.event_type == event_type)

    if search:
        like = f'%{search}%'
        q = q.filter(
            db.or_(
                CustomerActivity.search_query.ilike(like),
                CustomerActivity.category_name.ilike(like),
                CustomerActivity.brand_name.ilike(like),
            )
        )

    total = q.count()
    rows = (
        q.order_by(desc(CustomerActivity.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return jsonify({
        'success': True,
        'data': [r.to_dict() for r in rows],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': (total + per_page - 1) // per_page if total else 0,
        },
    })


@customer_activity_bp.route('/admin/customer-activity/summary', methods=['GET'])
@jwt_required()
def customer_activity_summary():
    denied = _admin_guard()
    if denied:
        return denied

    date_from, date_to = parse_date_range(request.args)
    limit = max(1, min(request.args.get('limit', default=20, type=int) or 20, 100))

    base = CustomerActivity.query.filter(
        CustomerActivity.created_at >= date_from,
        CustomerActivity.created_at <= date_to,
    )

    # Топ поисков — LOWER(search_query) чтобы «касса» = «Касса».
    top_searches_rows = (
        db.session.query(
            func.lower(CustomerActivity.search_query).label('q'),
            func.count(CustomerActivity.id).label('cnt'),
            func.max(CustomerActivity.results_count).label('last_results'),
        )
        .filter(
            CustomerActivity.created_at >= date_from,
            CustomerActivity.created_at <= date_to,
            CustomerActivity.event_type == 'search',
            CustomerActivity.search_query.isnot(None),
        )
        .group_by('q')
        .order_by(desc('cnt'))
        .limit(limit)
        .all()
    )

    # Топ категорий: сначала по id (актуальные), NULL — сложим отдельно
    top_categories_rows = (
        db.session.query(
            CustomerActivity.category_id,
            func.max(CustomerActivity.category_name).label('name'),
            func.max(CustomerActivity.category_slug).label('slug'),
            func.count(CustomerActivity.id).label('cnt'),
        )
        .filter(
            CustomerActivity.created_at >= date_from,
            CustomerActivity.created_at <= date_to,
            CustomerActivity.event_type == 'category_view',
        )
        .group_by(CustomerActivity.category_id)
        .order_by(desc('cnt'))
        .limit(limit)
        .all()
    )

    top_brands_rows = (
        db.session.query(
            CustomerActivity.brand_id,
            func.max(CustomerActivity.brand_name).label('name'),
            func.count(CustomerActivity.id).label('cnt'),
        )
        .filter(
            CustomerActivity.created_at >= date_from,
            CustomerActivity.created_at <= date_to,
            CustomerActivity.event_type == 'brand_view',
        )
        .group_by(CustomerActivity.brand_id)
        .order_by(desc('cnt'))
        .limit(limit)
        .all()
    )

    totals = dict(
        db.session.query(
            CustomerActivity.event_type,
            func.count(CustomerActivity.id),
        )
        .filter(
            CustomerActivity.created_at >= date_from,
            CustomerActivity.created_at <= date_to,
        )
        .group_by(CustomerActivity.event_type)
        .all()
    )

    return jsonify({
        'success': True,
        'totals': {
            'search': totals.get('search', 0),
            'category_view': totals.get('category_view', 0),
            'brand_view': totals.get('brand_view', 0),
        },
        'top_searches': [
            {'query': r.q, 'count': r.cnt, 'last_results': r.last_results}
            for r in top_searches_rows
        ],
        'top_categories': [
            {'category_id': r.category_id, 'name': r.name, 'slug': r.slug, 'count': r.cnt}
            for r in top_categories_rows
        ],
        'top_brands': [
            {'brand_id': r.brand_id, 'name': r.name, 'count': r.cnt}
            for r in top_brands_rows
        ],
    })
