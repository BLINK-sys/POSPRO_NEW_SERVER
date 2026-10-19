"""
CRUD универсальных справочников для «опросника при переходе стадии»:
Dictionary (code/label/order) + DictionaryItem (dict_id/name/order/is_active).

Access: читать может любой admin/system; создавать/редактировать/удалять —
только owner или can_manage_pipelines (та же привычная связка «настройщик
CRM-структуры», что для воронок, проектов и источников).

Endpoints:
  GET    /api/admin/dictionaries                           — список всех (с items_count)
  GET    /api/admin/dictionaries/<id>                      — один справочник (с items)
  POST   /api/admin/dictionaries                           — создать (code/label/order_pos)
  PUT    /api/admin/dictionaries/<id>                      — обновить
  DELETE /api/admin/dictionaries/<id>                      — удалить (CASCADE на items)
  GET    /api/admin/dictionaries/<id>/items                — items справочника
  POST   /api/admin/dictionaries/<id>/items                — создать item
  PUT    /api/admin/dictionary-items/<id>                  — обновить item
  DELETE /api/admin/dictionary-items/<id>                  — удалить item
"""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from extensions import db
from models.dictionary import Dictionary, DictionaryItem


dictionaries_bp = Blueprint('dictionaries', __name__)


CODE_RE = re.compile(r'^[a-z0-9_]{1,64}$')


def _check_admin_or_system():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _check_can_manage():
    from services.perms import can_manage_pipelines as _cmp
    try:
        uid = int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        uid = None
    if not _cmp(uid):
        return jsonify({'error': 'Настройка справочников доступна только владельцу и уполномоченным'}), 403
    return None


def _parse_dict_payload(data: dict, partial: bool = False):
    fields: dict = {}
    label = (data.get('label') or '').strip() or None
    if not partial and not label:
        return False, 'Название справочника обязательно', {}
    if label is not None:
        if len(label) > 255:
            return False, 'Название слишком длинное (макс 255)', {}
        fields['label'] = label

    if 'code' in data:
        code = (data.get('code') or '').strip().lower() or None
        if not partial and not code:
            return False, 'code справочника обязателен (ascii, _0-9)', {}
        if code is not None:
            if not CODE_RE.match(code):
                return False, 'code: только a-z, 0-9, _, до 64 символов', {}
            fields['code'] = code

    if 'order_pos' in data:
        try:
            fields['order_pos'] = int(data['order_pos'] or 0)
        except (TypeError, ValueError):
            return False, 'order_pos должен быть числом', {}
    return True, None, fields


def _parse_item_payload(data: dict, partial: bool = False):
    fields: dict = {}
    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название элемента обязательно', {}
    if name is not None:
        if len(name) > 255:
            return False, 'Название слишком длинное (макс 255)', {}
        fields['name'] = name
    if 'order_pos' in data:
        try:
            fields['order_pos'] = int(data['order_pos'] or 0)
        except (TypeError, ValueError):
            return False, 'order_pos должен быть числом', {}
    if 'is_active' in data:
        fields['is_active'] = bool(data['is_active'])
    return True, None, fields


# ---------------------------------------------------------------------------
# Dictionaries
# ---------------------------------------------------------------------------

@dictionaries_bp.route('/admin/dictionaries', methods=['GET'],
                       strict_slashes=False)
@jwt_required()
def list_dicts():
    err = _check_admin_or_system()
    if err:
        return err
    items = Dictionary.query.order_by(Dictionary.order_pos, Dictionary.label).all()
    # items_count одним запросом
    counts: dict[int, int] = {}
    if items:
        rows = db.session.query(
            DictionaryItem.dict_id, db.func.count(DictionaryItem.id),
        ).filter(
            DictionaryItem.dict_id.in_([d.id for d in items]),
        ).group_by(DictionaryItem.dict_id).all()
        counts = {did: int(c) for did, c in rows}
    out = []
    for d in items:
        row = d.to_dict()
        row['items_count'] = counts.get(d.id, 0)
        out.append(row)
    return jsonify({'success': True, 'dictionaries': out}), 200


@dictionaries_bp.route('/admin/dictionaries/<int:did>', methods=['GET'],
                       strict_slashes=False)
@jwt_required()
def get_dict(did):
    err = _check_admin_or_system()
    if err:
        return err
    d = Dictionary.query.get(did)
    if not d:
        return jsonify({'error': 'Справочник не найден'}), 404
    return jsonify({'success': True, 'dictionary': d.to_dict(with_items=True)}), 200


@dictionaries_bp.route('/admin/dictionaries', methods=['POST'],
                       strict_slashes=False)
@jwt_required()
def create_dict():
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    data = request.get_json() or {}
    ok, msg, fields = _parse_dict_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400
    if Dictionary.query.filter_by(code=fields['code']).first():
        return jsonify({'error': f'Справочник с code={fields["code"]!r} уже существует'}), 409
    d = Dictionary(**fields)
    db.session.add(d)
    db.session.commit()
    return jsonify({'success': True, 'dictionary': d.to_dict()}), 201


@dictionaries_bp.route('/admin/dictionaries/<int:did>', methods=['PUT'],
                       strict_slashes=False)
@jwt_required()
def update_dict(did):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    d = Dictionary.query.get(did)
    if not d:
        return jsonify({'error': 'Справочник не найден'}), 404
    data = request.get_json() or {}
    ok, msg, fields = _parse_dict_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400
    if 'code' in fields and fields['code'] != d.code:
        if Dictionary.query.filter(Dictionary.code == fields['code'],
                                    Dictionary.id != did).first():
            return jsonify({'error': 'code занят другим справочником'}), 409
    for k, v in fields.items():
        setattr(d, k, v)
    db.session.commit()
    return jsonify({'success': True, 'dictionary': d.to_dict()}), 200


@dictionaries_bp.route('/admin/dictionaries/<int:did>', methods=['DELETE'],
                       strict_slashes=False)
@jwt_required()
def delete_dict(did):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    d = Dictionary.query.get(did)
    if not d:
        return jsonify({'error': 'Справочник не найден'}), 404
    # Удаление справочника. Items уйдут CASCADE. Значения в
    # deal.survey_values[<code>] остаются (JSONB), но будут показываться
    # «несуществующий элемент» на фронте — ок, не критично для MVP.
    db.session.delete(d)
    db.session.commit()
    return jsonify({'success': True}), 200


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@dictionaries_bp.route('/admin/dictionaries/<int:did>/items',
                       methods=['GET'], strict_slashes=False)
@jwt_required()
def list_items(did):
    err = _check_admin_or_system()
    if err:
        return err
    if not Dictionary.query.get(did):
        return jsonify({'error': 'Справочник не найден'}), 404
    rows = DictionaryItem.query.filter_by(dict_id=did)\
        .order_by(DictionaryItem.order_pos, DictionaryItem.name).all()
    return jsonify({'success': True, 'items': [r.to_dict() for r in rows]}), 200


@dictionaries_bp.route('/admin/dictionaries/<int:did>/items',
                       methods=['POST'], strict_slashes=False)
@jwt_required()
def create_item(did):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    if not Dictionary.query.get(did):
        return jsonify({'error': 'Справочник не найден'}), 404
    data = request.get_json() or {}
    ok, msg, fields = _parse_item_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400
    dup = DictionaryItem.query.filter(
        DictionaryItem.dict_id == did,
        db.func.lower(DictionaryItem.name) == fields['name'].lower(),
    ).first()
    if dup:
        return jsonify({'error': 'Элемент с таким названием уже существует'}), 409
    item = DictionaryItem(dict_id=did, **fields)
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'item': item.to_dict()}), 201


@dictionaries_bp.route('/admin/dictionary-items/<int:iid>',
                       methods=['PUT'], strict_slashes=False)
@jwt_required()
def update_item(iid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    item = DictionaryItem.query.get(iid)
    if not item:
        return jsonify({'error': 'Элемент не найден'}), 404
    data = request.get_json() or {}
    ok, msg, fields = _parse_item_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400
    if 'name' in fields and fields['name'].lower() != (item.name or '').lower():
        dup = DictionaryItem.query.filter(
            DictionaryItem.dict_id == item.dict_id,
            db.func.lower(DictionaryItem.name) == fields['name'].lower(),
            DictionaryItem.id != iid,
        ).first()
        if dup:
            return jsonify({'error': 'Элемент с таким названием уже существует'}), 409
    for k, v in fields.items():
        setattr(item, k, v)
    db.session.commit()
    return jsonify({'success': True, 'item': item.to_dict()}), 200


@dictionaries_bp.route('/admin/dictionary-items/<int:iid>',
                       methods=['DELETE'], strict_slashes=False)
@jwt_required()
def delete_item(iid):
    err = _check_admin_or_system()
    if err:
        return err
    err = _check_can_manage()
    if err:
        return err
    item = DictionaryItem.query.get(iid)
    if not item:
        return jsonify({'error': 'Элемент не найден'}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True}), 200


# ---------------------------------------------------------------------------
# Pipeline survey helpers
# ---------------------------------------------------------------------------

@dictionaries_bp.route('/admin/deal-pipelines/<int:pid>/survey-dicts',
                       methods=['GET'], strict_slashes=False)
@jwt_required()
def pipeline_survey_dicts(pid):
    """
    Возвращает union всех required_dict_codes со всех стадий воронки pid,
    развёрнутый до объектов Dictionary (с items). Нужен для карточки
    «Информация» сделки — чтобы показать селекты по ВСЕМ справочникам
    воронки, не только текущей стадии.
    """
    err = _check_admin_or_system()
    if err:
        return err
    from models.deal_pipeline import DealStage
    stages = DealStage.query.filter_by(pipeline_id=pid).all()
    codes: set[str] = set()
    for s in stages:
        for c in (s.required_dict_codes or []):
            if isinstance(c, str):
                codes.add(c)
    if not codes:
        return jsonify({'success': True, 'dictionaries': []}), 200
    dicts = Dictionary.query.filter(Dictionary.code.in_(list(codes)))\
        .order_by(Dictionary.order_pos, Dictionary.label).all()
    return jsonify({
        'success': True,
        'dictionaries': [d.to_dict(with_items=True) for d in dicts],
    }), 200
