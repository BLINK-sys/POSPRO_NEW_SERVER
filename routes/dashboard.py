import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.user import User
from models.systemuser import SystemUser
from models.site_visitor import SiteVisitor
from models.site_request import SiteRequest
from models.product_view import ProductView

dashboard_bp = Blueprint('dashboard', __name__)


def parse_date_range(args):
    """Парсит параметры периода и возвращает (date_from, date_to)."""
    period = args.get('period', 'today')
    now = datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'custom':
        date_from_str = args.get('date_from')
        date_to_str = args.get('date_to')
        if date_from_str and date_to_str:
            date_from = datetime.datetime.strptime(date_from_str, '%Y-%m-%d')
            date_to = datetime.datetime.strptime(date_to_str, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59
            )
        else:
            date_from = today_start
            date_to = now
    elif period == 'week':
        date_from = today_start - datetime.timedelta(days=today_start.weekday())
        date_to = now
    elif period == 'month':
        date_from = today_start.replace(day=1)
        date_to = now
    elif period == '3months':
        month = today_start.month - 3
        year = today_start.year
        if month <= 0:
            month += 12
            year -= 1
        date_from = today_start.replace(year=year, month=month, day=1)
        date_to = now
    else:  # today
        date_from = today_start
        date_to = now

    return date_from, date_to


# === Публичный эндпоинт: трекинг визитов ===

@dashboard_bp.route('/track-visit', methods=['POST'])
def track_visit():
    """Записывает уникального посетителя (по IP + device_type за день)."""
    data = request.get_json(silent=True) or {}

    # IP и User-Agent приходят из Next.js middleware в теле запроса
    ip = data.get('ip', '')
    if not ip:
        ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    if not ip:
        ip = request.headers.get('X-Real-Ip', request.remote_addr or 'unknown')

    user_agent = data.get('user_agent', '') or request.headers.get('User-Agent', '')

    # Фильтруем ботов
    ua_lower = user_agent.lower()
    bot_keywords = [
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
    ]
    is_bot = not user_agent or any(kw in ua_lower for kw in bot_keywords)

    if is_bot:
        device_type = 'bot'
    else:
        # Определяем тип устройства по User-Agent
        mobile_keywords = ['Mobile', 'Android', 'iPhone', 'iPad', 'iPod', 'Opera Mini', 'IEMobile']
        device_type = 'mobile' if any(kw in user_agent for kw in mobile_keywords) else 'web'

    # Проверяем: есть ли уже запись за сегодня с этим IP + device_type
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    existing = SiteVisitor.query.filter(
        SiteVisitor.ip_address == ip,
        SiteVisitor.device_type == device_type,
        SiteVisitor.visited_at >= today_start
    ).first()

    if not existing:
        visitor = SiteVisitor(
            ip_address=ip,
            device_type=device_type,
            user_agent=user_agent,
            visited_at=datetime.datetime.now()
        )
        db.session.add(visitor)
        db.session.commit()

    return jsonify({'success': True}), 200


# === Публичный эндпоинт: трекинг заявок ===

@dashboard_bp.route('/track-request', methods=['POST'])
def track_request():
    """Записывает заявку (оформление заказа или уточнение цены)."""
    data = request.get_json() or {}

    request_type = data.get('request_type')
    if request_type not in ('order', 'price_inquiry'):
        return jsonify({'error': 'Invalid request_type'}), 400

    site_request = SiteRequest(
        request_type=request_type,
        customer_name=data.get('customer_name'),
        customer_phone=data.get('customer_phone'),
        customer_email=data.get('customer_email'),
        product_name=data.get('product_name'),
        product_slug=data.get('product_slug'),
        total_amount=data.get('total_amount'),
        assigned_to=data.get('assigned_to'),
        created_at=datetime.datetime.now()
    )
    db.session.add(site_request)
    db.session.commit()

    return jsonify({'success': True}), 200


# === Админский эндпоинт: статистика ===

@dashboard_bp.route('/dashboard-stats', methods=['GET'])
@jwt_required()
def dashboard_stats():
    """Возвращает статистику для дашборда."""
    jwt_data = get_jwt()
    role = jwt_data.get('role', 'client')

    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403

    date_from, date_to = parse_date_range(request.args)

    # Пользователи (общее количество — не зависит от периода)
    total_clients = User.query.filter(
        db.or_(User.is_wholesale == False, User.is_wholesale.is_(None))
    ).count()
    total_wholesale = User.query.filter_by(is_wholesale=True).count()
    total_system_users = SystemUser.query.count()

    # Уникальные посетители за период (COUNT DISTINCT ip)
    web_visitors = db.session.query(
        db.func.count(db.distinct(SiteVisitor.ip_address))
    ).filter(
        SiteVisitor.device_type == 'web',
        SiteVisitor.visited_at >= date_from,
        SiteVisitor.visited_at <= date_to
    ).scalar() or 0

    mobile_visitors = db.session.query(
        db.func.count(db.distinct(SiteVisitor.ip_address))
    ).filter(
        SiteVisitor.device_type == 'mobile',
        SiteVisitor.visited_at >= date_from,
        SiteVisitor.visited_at <= date_to
    ).scalar() or 0

    bot_count = db.session.query(
        db.func.count(db.distinct(SiteVisitor.ip_address))
    ).filter(
        SiteVisitor.device_type == 'bot',
        SiteVisitor.visited_at >= date_from,
        SiteVisitor.visited_at <= date_to
    ).scalar() or 0

    bot_total = db.session.query(
        db.func.count(SiteVisitor.id)
    ).filter(
        SiteVisitor.device_type == 'bot'
    ).scalar() or 0

    # Заявки за период
    orders_count = SiteRequest.query.filter(
        SiteRequest.request_type == 'order',
        SiteRequest.created_at >= date_from,
        SiteRequest.created_at <= date_to
    ).count()

    price_inquiries_count = SiteRequest.query.filter(
        SiteRequest.request_type == 'price_inquiry',
        SiteRequest.created_at >= date_from,
        SiteRequest.created_at <= date_to
    ).count()

    # Просмотры товаров за период
    product_views_count = db.session.query(
        db.func.count(ProductView.id)
    ).filter(
        ProductView.viewed_at >= date_from,
        ProductView.viewed_at <= date_to
    ).scalar() or 0

    # Последние заявки (5 штук, без фильтра по дате)
    recent_requests = SiteRequest.query.order_by(
        SiteRequest.created_at.desc()
    ).limit(5).all()

    recent_list = [{
        'id': r.id,
        'request_type': r.request_type,
        'customer_name': r.customer_name,
        'customer_phone': r.customer_phone,
        'product_name': r.product_name,
        'total_amount': r.total_amount,
        'assigned_to': r.assigned_to,
        'created_at': r.created_at.isoformat() if r.created_at else None
    } for r in recent_requests]

    return jsonify({
        'success': True,
        'data': {
            'users': {
                'total_clients': total_clients,
                'total_wholesale': total_wholesale,
                'total_system_users': total_system_users
            },
            'visitors': {
                'web': web_visitors,
                'mobile': mobile_visitors,
                'bots': bot_count,
                'bots_total': bot_total
            },
            'requests': {
                'orders': orders_count,
                'price_inquiries': price_inquiries_count
            },
            'product_views': product_views_count,
            'recent_requests': recent_list
        }
    })


@dashboard_bp.route('/visitor-details', methods=['GET'])
@jwt_required()
def visitor_details():
    """Возвращает список посетителей по типу устройства."""
    jwt_data = get_jwt()
    role = jwt_data.get('role', 'client')

    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403

    device_type = request.args.get('device_type', 'web')
    show_all = request.args.get('all', 'false') == 'true'

    if show_all:
        visitors = SiteVisitor.query.filter(
            SiteVisitor.device_type == device_type
        ).order_by(SiteVisitor.visited_at.desc()).limit(500).all()
    else:
        date_from, date_to = parse_date_range(request.args)
        visitors = SiteVisitor.query.filter(
            SiteVisitor.device_type == device_type,
            SiteVisitor.visited_at >= date_from,
            SiteVisitor.visited_at <= date_to
        ).order_by(SiteVisitor.visited_at.desc()).limit(500).all()

    rows = [{
        'ip': v.ip_address,
        'user_agent': v.user_agent[:150] if v.user_agent else None,
        'visited_at': v.visited_at.isoformat() if v.visited_at else None
    } for v in visitors]

    return jsonify({'success': True, 'data': rows})


# === Публичный эндпоинт: трекинг просмотров товаров ===

@dashboard_bp.route('/track-product-view', methods=['POST'])
def track_product_view():
    """Записывает просмотр товара (кроме системных пользователей)."""
    data = request.get_json(silent=True) or {}

    product_id = data.get('product_id')
    if not product_id:
        return jsonify({'error': 'product_id required'}), 400

    # Фильтруем ботов по user_agent
    user_agent = data.get('user_agent', '')
    ua_lower = user_agent.lower()
    bot_keywords = [
        'bot', 'crawl', 'spider', 'slurp', 'scraper', 'fetch',
        'curl', 'wget', 'python-requests', 'googlebot', 'bingbot',
        'yandexbot', 'semrushbot', 'ahrefsbot', 'headlesschrome',
        'phantomjs', 'selenium', 'puppeteer', 'lighthouse',
    ]
    if not user_agent or any(kw in ua_lower for kw in bot_keywords):
        return jsonify({'success': True, 'filtered': 'bot'}), 200

    ip = data.get('ip', request.remote_addr or 'unknown')

    view = ProductView(
        product_id=product_id,
        product_name=data.get('product_name'),
        product_slug=data.get('product_slug'),
        ip_address=ip,
        user_agent=user_agent,
        viewed_at=datetime.datetime.now()
    )
    db.session.add(view)
    db.session.commit()

    return jsonify({'success': True}), 200


# === Админский эндпоинт: топ просматриваемых товаров ===

@dashboard_bp.route('/top-products', methods=['GET'])
@jwt_required()
def top_products():
    """Возвращает топ просматриваемых товаров за период."""
    jwt_data = get_jwt()
    role = jwt_data.get('role', 'client')

    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403

    date_from, date_to = parse_date_range(request.args)
    limit = int(request.args.get('limit', 20))

    # Группируем по product_id, считаем просмотры
    results = db.session.query(
        ProductView.product_id,
        ProductView.product_name,
        ProductView.product_slug,
        db.func.count(ProductView.id).label('views'),
        db.func.count(db.distinct(ProductView.ip_address)).label('unique_views')
    ).filter(
        ProductView.viewed_at >= date_from,
        ProductView.viewed_at <= date_to
    ).group_by(
        ProductView.product_id,
        ProductView.product_name,
        ProductView.product_slug
    ).order_by(
        db.desc('views')
    ).limit(limit).all()

    rows = [{
        'product_id': r.product_id,
        'product_name': r.product_name,
        'product_slug': r.product_slug,
        'views': r.views,
        'unique_views': r.unique_views
    } for r in results]

    total_views = db.session.query(
        db.func.count(ProductView.id)
    ).filter(
        ProductView.viewed_at >= date_from,
        ProductView.viewed_at <= date_to
    ).scalar() or 0

    return jsonify({
        'success': True,
        'data': {
            'total_views': total_views,
            'products': rows
        }
    })
