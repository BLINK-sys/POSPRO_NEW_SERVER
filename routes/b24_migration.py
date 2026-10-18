"""
Админ-эндпоинты управления миграцией из Bitrix24.
Owner-only — ничего из этого обычным юзерам не нужно.

Пока минимум:
  GET /api/admin/b24-migration/mapping  — скачать JSON авто-маппинга,
      сохранённый fetch_mapping.py на /disk/b24_migration/
  GET /api/admin/b24-migration/status   — список записей b24_mirror
      агрегированный по entity_type (сколько сущностей импортировано).
"""

import json

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text as sql_text

from extensions import db
from models.systemuser import SystemUser
from models.b24_mirror import B24Mirror


b24_migration_bp = Blueprint('b24_migration', __name__)


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
    """Отдаёт финальный маппинг из таблицы b24_meta (сохранён fix_mapping-ом)."""
    err = _owner_only()
    if err:
        return err
    try:
        row = db.session.execute(
            sql_text("SELECT value FROM b24_meta WHERE key='mapping'")
        ).fetchone()
    except Exception as e:
        return jsonify({
            'error': 'b24_meta table missing or query failed',
            'details': str(e),
        }), 404
    if not row:
        return jsonify({
            'error': 'Mapping not found. Запусти Render Job '
                     '`python -u -m migrations.bitrix24.fix_mapping`.',
        }), 404
    value = row[0]
    # Postgres JSONB — psycopg уже вернул dict.
    if isinstance(value, str):
        value = json.loads(value)
    return jsonify(value), 200


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
