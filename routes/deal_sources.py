"""
CRUD справочника «Источник сделки» (`DealSource`).

Access: любой admin/system может читать (чтобы выбрать в селекте «Новая
сделка»); редактировать/создавать/удалять — только owner или юзер с
`can_manage_pipelines` (та же привычная связка «настройщик CRM-структуры»,
что для воронок и проектов).

Endpoints:
  GET    /api/admin/deal-sources            список всех
  POST   /api/admin/deal-sources            создать
  PUT    /api/admin/deal-sources/<id>       обновить (name/color/order/is_active)
  DELETE /api/admin/deal-sources/<id>       удалить (сделки, что ссылались,
                                             получат source_id = NULL — SET NULL)
"""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from extensions import db
from models.deal_source import DealSource, DealSourceVariant


deal_sources_bp = Blueprint('deal_sources', __name__)


HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _check_admin_or_system():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _check_can_manage():
    """Только owner или can_manage_pipelines."""
    from services.perms import can_manage_pipelines as _cmp
    try:
        uid = int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        uid = None
    if not _cmp(uid):
        return jsonify({'error': 'Настройка источников доступна только владельцу и уполномоченным'}), 403
    return None


def _parse_payload(data: dict, partial: bool = False):
    fields: dict = {}
    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название источника обязательно', {}
    if name is not None:
        if len(name) > 128:
            return False, 'Название слишком длинное (макс 128)', {}
        fields['name'] = name

    if 'color' in data:
        color = (data.get('color') or '').strip() or None
        if color and not HEX_RE.match(color):
            return False, 'Цвет должен быть #RRGGBB', {}
        fields['color'] = color

    if 'sort_order' in data:
        try:
            fields['sort_order'] = int(data['sort_order'] or 0)
        except (TypeError, ValueError):
            return False, 'sort_order должен быть числом', {}

    if 'is_active' in data:
        fields['is_active'] = bool(data['is_active'])

    return True, None, fields


@deal_sources_bp.route('/admin/deal-sources', methods=['GET'])
@jwt_required()
def list_sources():
    err = _check_admin_or_system()
    if err:
        return err
    items = DealSource.query.order_by(DealSource.sort_order, DealSource.name).all()
    return jsonify({'success': True, 'sources': [s.to_dict() for s in items]}), 200


@deal_sources_bp.route('/admin/deal-sources', methods=['POST'])
@jwt_required()
def create_source():
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    dup = DealSource.query.filter(
        db.func.lower(DealSource.name) == fields['name'].lower(),
    ).first()
    if dup:
        return jsonify({'error': 'Источник с таким названием уже существует'}), 409

    s = DealSource(**fields)
    db.session.add(s)
    db.session.commit()
    return jsonify({'success': True, 'source': s.to_dict()}), 201


@deal_sources_bp.route('/admin/deal-sources/<int:sid>', methods=['PUT'])
@jwt_required()
def update_source(sid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err

    s = DealSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in fields and fields['name'].lower() != (s.name or '').lower():
        dup = DealSource.query.filter(
            db.func.lower(DealSource.name) == fields['name'].lower(),
            DealSource.id != sid,
        ).first()
        if dup:
            return jsonify({'error': 'Источник с таким названием уже существует'}), 409

    for k, v in fields.items():
        setattr(s, k, v)
    db.session.commit()
    return jsonify({'success': True, 'source': s.to_dict()}), 200


@deal_sources_bp.route('/admin/deal-sources/<int:sid>', methods=['DELETE'])
@jwt_required()
def delete_source(sid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err

    s = DealSource.query.get(sid)
    if not s:
        return jsonify({'error': 'Источник не найден'}), 404

    # SET NULL в FK → сделки не удаляются, просто теряют источник.
    # crm_ingest_source.default_deal_source_id тоже обнуляется (SET NULL).
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# DealSourceVariant — «Дополнительно об источнике» (дочерний справочник)
# ============================================================================

def _parse_variant_payload(data: dict, partial: bool = False):
    fields: dict = {}
    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название варианта обязательно', {}
    if name is not None:
        if len(name) > 500:
            return False, 'Название слишком длинное (макс 500)', {}
        fields['name'] = name
    if 'order_pos' in data:
        try:
            fields['order_pos'] = int(data['order_pos'] or 0)
        except (TypeError, ValueError):
            return False, 'order_pos должен быть числом', {}
    return True, None, fields


@deal_sources_bp.route('/admin/deal-sources/<int:sid>/variants',
                       methods=['GET'], strict_slashes=False)
@jwt_required()
def list_variants(sid):
    err = _check_admin_or_system()
    if err:
        return err
    if not DealSource.query.get(sid):
        return jsonify({'error': 'Источник не найден'}), 404
    rows = DealSourceVariant.query.filter_by(parent_source_id=sid)\
        .order_by(DealSourceVariant.order_pos, DealSourceVariant.name).all()
    return jsonify({'success': True, 'variants': [v.to_dict() for v in rows]}), 200


@deal_sources_bp.route('/admin/deal-sources/<int:sid>/variants',
                       methods=['POST'], strict_slashes=False)
@jwt_required()
def create_variant(sid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    if not DealSource.query.get(sid):
        return jsonify({'error': 'Источник не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_variant_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    dup = DealSourceVariant.query.filter(
        DealSourceVariant.parent_source_id == sid,
        db.func.lower(DealSourceVariant.name) == fields['name'].lower(),
    ).first()
    if dup:
        return jsonify({'error': 'Такой вариант уже существует'}), 409

    v = DealSourceVariant(parent_source_id=sid, **fields)
    db.session.add(v)
    db.session.commit()
    return jsonify({'success': True, 'variant': v.to_dict()}), 201


@deal_sources_bp.route('/admin/deal-source-variants/<int:vid>',
                       methods=['PUT'], strict_slashes=False)
@jwt_required()
def update_variant(vid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err

    v = DealSourceVariant.query.get(vid)
    if not v:
        return jsonify({'error': 'Вариант не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_variant_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in fields and fields['name'].lower() != (v.name or '').lower():
        dup = DealSourceVariant.query.filter(
            DealSourceVariant.parent_source_id == v.parent_source_id,
            db.func.lower(DealSourceVariant.name) == fields['name'].lower(),
            DealSourceVariant.id != vid,
        ).first()
        if dup:
            return jsonify({'error': 'Такой вариант уже существует'}), 409

    for k, val in fields.items():
        setattr(v, k, val)
    db.session.commit()
    return jsonify({'success': True, 'variant': v.to_dict()}), 200


@deal_sources_bp.route('/admin/deal-source-variants/<int:vid>',
                       methods=['DELETE'], strict_slashes=False)
@jwt_required()
def delete_variant(vid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    v = DealSourceVariant.query.get(vid)
    if not v:
        return jsonify({'error': 'Вариант не найден'}), 404
    db.session.delete(v)
    db.session.commit()
    return jsonify({'success': True}), 200
