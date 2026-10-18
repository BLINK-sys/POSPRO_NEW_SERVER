"""
CRUD для справочника компаний (`kp_company`). Shared-пул как и
`kp_clients`: все admin/system видят всех, все могут править/удалять.

Удаление:
- при удалении компании `kp_client.company_id` ставится в NULL
  (SET NULL в SQL) — сотрудники остаются
- на этой стадии не блокируем удаление по сделкам: FK в `deal.company_id`
  тоже SET NULL. Если позже понадобится — поднимем 409 как в kp_clients.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy import or_, func

from extensions import db
from models.kp_company import KpCompany
from models.kp_client import KpClient
from models.systemuser import SystemUser


kp_companies_bp = Blueprint('kp_companies', __name__)


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _validate(data: dict, *, partial: bool = False):
    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название компании обязательно', {}
    out = {
        'name': name,
        'bin': (data.get('bin') or '').strip() or None,
        'address': (data.get('address') or '').strip() or None,
        'website': (data.get('website') or '').strip() or None,
        'phone': (data.get('phone') or '').strip() or None,
        'email': (data.get('email') or '').strip() or None,
        'note': (data.get('note') or '').strip() or None,
    }
    return True, None, out


def _enrich(company_dicts: list[dict]) -> list[dict]:
    """Проставляет creator (имя+email) и counts (сколько контактов+сделок)."""
    if not company_dicts:
        return company_dicts
    ids = [c['id'] for c in company_dicts]

    # Контактов на компанию
    rows = (
        db.session.query(KpClient.company_id, func.count(KpClient.id))
        .filter(KpClient.company_id.in_(ids))
        .group_by(KpClient.company_id)
        .all()
    )
    clients_count = {cid: cnt for cid, cnt in rows}

    # Авторы — одной выборкой.
    creator_ids = {c.get('created_by') for c in company_dicts if c.get('created_by')}
    creators_by_id: dict[int, dict] = {}
    if creator_ids:
        for u in SystemUser.query.filter(SystemUser.id.in_(creator_ids)).all():
            # В модели SystemUser только одно поле full_name, без разделения
            # на first/last — используем его как есть, с fallback на email.
            creators_by_id[u.id] = {
                'id': u.id,
                'name': (u.full_name or '').strip() or u.email,
                'email': u.email,
            }

    for c in company_dicts:
        c['clients_count'] = clients_count.get(c['id'], 0)
        c['creator'] = creators_by_id.get(c.get('created_by'))
    return company_dicts


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

@kp_companies_bp.route('/admin/kp-companies', methods=['GET'])
@jwt_required()
def list_companies():
    err = _check_admin_role()
    if err:
        return err

    q = KpCompany.query
    search = (request.args.get('q') or '').strip()
    if search:
        like = f'%{search.lower()}%'
        q = q.filter(or_(
            func.lower(KpCompany.name).like(like),
            func.lower(func.coalesce(KpCompany.bin, '')).like(like),
            func.lower(func.coalesce(KpCompany.phone, '')).like(like),
            func.lower(func.coalesce(KpCompany.email, '')).like(like),
        ))

    total = q.count()
    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = max(request.args.get('offset', 0, type=int), 0)

    rows = q.order_by(KpCompany.updated_at.desc()).limit(limit).offset(offset).all()
    companies = _enrich([c.to_dict() for c in rows])

    return jsonify({
        'success': True,
        'companies': companies,
        'total': total,
        'limit': limit,
        'offset': offset,
    }), 200


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

@kp_companies_bp.route('/admin/kp-companies/<int:cid>', methods=['GET'])
@jwt_required()
def get_company(cid):
    err = _check_admin_role()
    if err:
        return err
    c = KpCompany.query.get_or_404(cid)
    enriched = _enrich([c.to_dict()])[0]

    # Прицельная выдача сотрудников — для карточки компании.
    clients = (
        KpClient.query.filter(KpClient.company_id == cid)
        .order_by(KpClient.full_name.asc().nulls_last())
        .all()
    )
    enriched['clients'] = [cl.to_dict() for cl in clients]
    return jsonify({'success': True, 'company': enriched}), 200


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

@kp_companies_bp.route('/admin/kp-companies', methods=['POST'])
@jwt_required()
def create_company():
    err = _check_admin_role()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    ok, msg, fields = _validate(data, partial=False)
    if not ok:
        return jsonify({'error': msg}), 400

    try:
        creator_id = int(get_jwt_identity() or 0) or None
    except (TypeError, ValueError):
        creator_id = None

    c = KpCompany(created_by=creator_id, **fields)
    db.session.add(c)
    db.session.commit()
    return jsonify({'success': True, 'company': c.to_dict()}), 201


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

@kp_companies_bp.route('/admin/kp-companies/<int:cid>', methods=['PUT'])
@jwt_required()
def update_company(cid):
    err = _check_admin_role()
    if err:
        return err

    c = KpCompany.query.get_or_404(cid)
    data = request.get_json(silent=True) or {}
    ok, msg, fields = _validate(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    for k, v in fields.items():
        if v is not None or k in data:  # None разрешён как «очистить поле»
            setattr(c, k, v)
    db.session.commit()
    return jsonify({'success': True, 'company': c.to_dict()}), 200


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

@kp_companies_bp.route('/admin/kp-companies/<int:cid>', methods=['DELETE'])
@jwt_required()
def delete_company(cid):
    err = _check_admin_role()
    if err:
        return err
    c = KpCompany.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True}), 200
