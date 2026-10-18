"""
Админ-эндпоинты управления миграцией из Bitrix24.
Owner-only — ничего из этого обычным юзерам не нужно.

Пока минимум:
  GET /api/admin/b24-migration/mapping  — скачать JSON авто-маппинга,
      сохранённый fetch_mapping.py на /disk/b24_migration/
  GET /api/admin/b24-migration/status   — список записей b24_mirror
      агрегированный по entity_type (сколько сущностей импортировано).
"""

import os
import json

from flask import Blueprint, jsonify, send_file, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models.systemuser import SystemUser
from models.b24_mirror import B24Mirror


b24_migration_bp = Blueprint('b24_migration', __name__)

MAPPING_PATH = '/disk/b24_migration/b24_mapping.json'


def _owner_only():
    try:
        uid = int(get_jwt_identity() or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'Нет доступа'}), 403
    user = SystemUser.query.get(uid)
    if not user or not user.is_owner:
        return jsonify({'error': 'Только для владельца системы'}), 403
    return None


@b24_migration_bp.route('/admin/b24-migration/mapping',
                        methods=['GET'], strict_slashes=False)
@jwt_required()
def download_mapping():
    err = _owner_only()
    if err:
        return err
    if not os.path.exists(MAPPING_PATH):
        return jsonify({
            'error': 'Mapping not found. Запусти Render Job '
                     '`python -u -m migrations.bitrix24.fetch_mapping`.',
            'expected_path': MAPPING_PATH,
        }), 404
    with open(MAPPING_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data), 200


@b24_migration_bp.route('/admin/b24-migration/status',
                        methods=['GET'], strict_slashes=False)
@jwt_required()
def status():
    err = _owner_only()
    if err:
        return err
    rows = db.session.query(
        B24Mirror.entity_type, db.func.count(B24Mirror.id),
    ).group_by(B24Mirror.entity_type).all()
    stats = {t: int(c) for t, c in rows}
    return jsonify({'success': True, 'imported': stats}), 200
