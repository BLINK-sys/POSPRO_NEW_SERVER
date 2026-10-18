"""
Аналитические эндпоинты для разделов «История» и «Источники» на
странице сделок.

  GET  /api/admin/deals/stats
       — Статы (всего/open/won/lost + суммы) по текущему фильтру.

  GET  /api/admin/deals/by-client
       — Группировка по клиенту: один клиент = одна строка с подсчётами.

  GET  /api/admin/deals/sources-stats
       — Агрегация по источникам (DealSource) + «без источника».
         Параметр `period` (days) ограничивает выборку по created_at.

Все три используют тот же _visible_deals_query, что и list — чтобы
видимость юзеру была одинаковой.
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func, case

from extensions import db
from models.deal import Deal
from models.kp_client import KpClient
from models.deal_source import DealSource
from models.deal_pipeline import DealPipeline, DealStage


deals_analytics_bp = Blueprint('deals_analytics', __name__)


# Переиспользуем helpers из routes.deals, но без import-cycle через функцию.
def _visibility_filter(q):
    """
    Применяет видимость из routes.deals._visible_deals_query. Импортируем
    отложенно чтобы не словить циклическую зависимость.
    """
    from routes.deals import _visible_deals_query, _current_role_and_id
    role, user_id = _current_role_and_id()
    base = _visible_deals_query(role, user_id)
    # base — Query над Deal. Нам нужны фильтры поверх базовой выборки.
    # Проще: берём список допустимых id (sub-query) и фильтруем.
    allowed_ids = base.with_entities(Deal.id).subquery()
    return q.filter(Deal.id.in_(db.session.query(allowed_ids.c.id)))


def _apply_filters(q):
    """Прикладывает query-параметры фильтров ко Query[Deal]."""
    created_after = request.args.get('created_after')
    created_before = request.args.get('created_before')
    status = request.args.get('status')
    pipeline_id = request.args.get('pipeline_id', type=int)
    stage_id = request.args.get('stage_id', type=int)
    client_id = request.args.get('client_id', type=int)
    company_id = request.args.get('company_id', type=int)
    responsible_id = request.args.get('responsible_id', type=int)
    source_id = request.args.get('source_id')  # int или 'none' для без источника
    amount_min = request.args.get('amount_min', type=float)
    amount_max = request.args.get('amount_max', type=float)
    search = (request.args.get('q') or '').strip()

    def _parse(iso):
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace('Z', '+00:00'))
        except Exception:
            return None

    ca = _parse(created_after)
    cb = _parse(created_before)
    if ca:
        q = q.filter(Deal.created_at >= ca)
    if cb:
        q = q.filter(Deal.created_at <= cb)
    if status in ('open', 'won', 'lost'):
        q = q.filter(Deal.status == status)
    if pipeline_id:
        q = q.filter(Deal.pipeline_id == pipeline_id)
    if stage_id:
        q = q.filter(Deal.stage_id == stage_id)
    if client_id:
        from models.kp_company import DealContact
        contact_deal_ids = db.session.query(DealContact.deal_id).filter(
            DealContact.client_id == client_id
        ).subquery()
        q = q.filter(db.or_(
            Deal.client_id == client_id,
            Deal.id.in_(contact_deal_ids),
        ))
    if company_id:
        q = q.filter(Deal.company_id == company_id)
    if responsible_id:
        q = q.filter(Deal.responsible_user_id == responsible_id)
    if source_id == 'none':
        q = q.filter(Deal.source_id.is_(None))
    elif source_id:
        try:
            q = q.filter(Deal.source_id == int(source_id))
        except (TypeError, ValueError):
            pass
    if amount_min is not None:
        q = q.filter(Deal.amount >= amount_min)
    if amount_max is not None:
        q = q.filter(Deal.amount <= amount_max)
    if search:
        like = f'%{search.lower()}%'
        q = q.filter(db.or_(
            db.func.lower(Deal.name).like(like),
            db.func.lower(db.func.coalesce(Deal.notes, '')).like(like),
        ))
    return q


def _role_check():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


# ---------------------------------------------------------------------------
# STATS: 4 плитки сверху «Истории».
# ---------------------------------------------------------------------------

@deals_analytics_bp.route('/admin/deals/stats', methods=['GET'],
                          strict_slashes=False)
@jwt_required()
def stats():
    err = _role_check()
    if err:
        return err

    q = _visibility_filter(_apply_filters(Deal.query))

    row = db.session.query(
        func.count(Deal.id),
        func.coalesce(
            func.sum(case((Deal.status == 'open', Deal.amount), else_=0)), 0,
        ),
        func.coalesce(
            func.sum(case((Deal.status == 'won', Deal.amount), else_=0)), 0,
        ),
        func.count(case((Deal.status == 'won', 1))),
    ).select_from(Deal).filter(
        Deal.id.in_(q.with_entities(Deal.id).subquery())
    ).one()
    total, sum_open, sum_won, won_count = row
    avg_won = float(sum_won) / won_count if won_count else 0.0

    return jsonify({
        'success': True,
        'total': int(total or 0),
        'sum_open': float(sum_open or 0),
        'sum_won': float(sum_won or 0),
        'avg_won': float(avg_won),
    }), 200


# ---------------------------------------------------------------------------
# BY-CLIENT: группировка «один клиент → все его сделки».
# ---------------------------------------------------------------------------

@deals_analytics_bp.route('/admin/deals/by-client', methods=['GET'],
                          strict_slashes=False)
@jwt_required()
def by_client():
    err = _role_check()
    if err:
        return err

    base = _visibility_filter(_apply_filters(Deal.query))
    ids_sub = base.with_entities(Deal.id).subquery()

    # Группируем по client_id. Для каждого клиента:
    # - count, open_count, won_count, lost_count
    # - sum_won
    # - last_at (max created_at)
    rows = db.session.query(
        Deal.client_id,
        func.count(Deal.id),
        func.count(case((Deal.status == 'open', 1))),
        func.count(case((Deal.status == 'won', 1))),
        func.count(case((Deal.status == 'lost', 1))),
        func.coalesce(
            func.sum(case((Deal.status == 'won', Deal.amount), else_=0)), 0,
        ),
        func.max(Deal.created_at),
    ).filter(
        Deal.id.in_(db.session.query(ids_sub.c.id)),
    ).group_by(Deal.client_id).all()

    client_ids = [r[0] for r in rows if r[0] is not None]
    clients_by_id = {}
    if client_ids:
        for c in KpClient.query.filter(KpClient.id.in_(client_ids)).all():
            clients_by_id[c.id] = c.display_name

    out = []
    for cid, total, nopen, nwon, nlost, sum_won, last_at in rows:
        name = clients_by_id.get(cid) if cid else '— без клиента —'
        out.append({
            'client_id': cid,
            'client_name': name,
            'total': int(total),
            'open': int(nopen),
            'won': int(nwon),
            'lost': int(nlost),
            'sum_won': float(sum_won or 0),
            'last_at': last_at.isoformat() if last_at else None,
        })

    # Сортировка по умолчанию — total DESC, затем last_at DESC
    out.sort(key=lambda x: (-x['total'], -(
        datetime.fromisoformat(x['last_at'].replace('Z', '+00:00')).timestamp()
        if x['last_at'] else 0
    )))

    # Простая серверная пагинация
    limit = min(request.args.get('limit', 50, type=int), 500)
    offset = max(request.args.get('offset', 0, type=int), 0)
    return jsonify({
        'success': True,
        'rows': out[offset:offset + limit],
        'total': len(out),
        'limit': limit,
        'offset': offset,
    }), 200


# ---------------------------------------------------------------------------
# SOURCES-STATS: таб «Источники».
# ---------------------------------------------------------------------------

@deals_analytics_bp.route('/admin/deals/sources-stats', methods=['GET'],
                          strict_slashes=False)
@jwt_required()
def sources_stats():
    """
    Агрегация по DealSource. Период берётся из `?months=N` (1,2,3,6,12)
    либо `?created_after=ISO` для кастома. Без параметров — за всё время.
    """
    err = _role_check()
    if err:
        return err

    months = request.args.get('months', type=int)
    created_after = request.args.get('created_after')

    q = Deal.query
    if created_after:
        try:
            dt = datetime.fromisoformat(created_after.replace('Z', '+00:00'))
            q = q.filter(Deal.created_at >= dt)
        except Exception:
            pass
    elif months:
        since = datetime.utcnow() - timedelta(days=30 * months)
        q = q.filter(Deal.created_at >= since)

    q = _visibility_filter(q)
    ids_sub = q.with_entities(Deal.id).subquery()

    rows = db.session.query(
        Deal.source_id,
        func.count(Deal.id),
        func.count(case((Deal.status == 'open', 1))),
        func.count(case((Deal.status == 'won', 1))),
        func.count(case((Deal.status == 'lost', 1))),
        func.coalesce(
            func.sum(case((Deal.status == 'won', Deal.amount), else_=0)), 0,
        ),
    ).filter(
        Deal.id.in_(db.session.query(ids_sub.c.id)),
    ).group_by(Deal.source_id).all()

    source_ids = [r[0] for r in rows if r[0] is not None]
    sources_by_id = {}
    if source_ids:
        for s in DealSource.query.filter(DealSource.id.in_(source_ids)).all():
            sources_by_id[s.id] = {'name': s.name, 'color': s.color}

    out = []
    totals = {'total': 0, 'open': 0, 'won': 0, 'lost': 0, 'sum_won': 0.0}
    for sid, total, nopen, nwon, nlost, sum_won in rows:
        src = sources_by_id.get(sid) if sid else None
        name = src['name'] if src else '— без источника —'
        color = src['color'] if src else None
        total = int(total); nopen = int(nopen); nwon = int(nwon); nlost = int(nlost)
        sum_won = float(sum_won or 0)
        decided = nwon + nlost
        conversion = (nwon / decided * 100) if decided else None
        avg_check = (sum_won / nwon) if nwon else 0.0

        out.append({
            'source_id': sid,
            'source_name': name,
            'source_color': color,
            'total': total,
            'open': nopen,
            'won': nwon,
            'lost': nlost,
            'sum_won': sum_won,
            'avg_check': avg_check,
            'conversion': conversion,  # None если не было закрытых
        })
        totals['total'] += total
        totals['open'] += nopen
        totals['won'] += nwon
        totals['lost'] += nlost
        totals['sum_won'] += sum_won

    # Сортировка — по total DESC по умолчанию
    out.sort(key=lambda x: -x['total'])
    decided_total = totals['won'] + totals['lost']
    totals['conversion'] = (
        (totals['won'] / decided_total * 100) if decided_total else None
    )
    totals['avg_check'] = (
        (totals['sum_won'] / totals['won']) if totals['won'] else 0.0
    )

    return jsonify({
        'success': True,
        'rows': out,
        'totals': totals,
    }), 200
