from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.catalog_visibility import CatalogVisibility
from extensions import db

catalog_visibility_bp = Blueprint('catalog_visibility', __name__)

VALID_TYPES = ('sidebar', 'main', 'slide')


def _get_all_visibility():
    """Вернуть словарь { sidebar: bool, main: bool, slide: bool }"""
    records = CatalogVisibility.query.all()
    result = {t: True for t in VALID_TYPES}
    for r in records:
        if r.catalog_type in VALID_TYPES:
            result[r.catalog_type] = r.enabled
    return result


# --- Публичный эндпоинт (без авторизации, для Header) ---

@catalog_visibility_bp.route('/catalog-visibility', methods=['GET'])
def get_public_catalog_visibility():
    """Получить видимость каталогов (публично, без авторизации)"""
    try:
        return jsonify({'success': True, 'visibility': _get_all_visibility()}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- Админские эндпоинты ---

@catalog_visibility_bp.route('/admin-catalog-visibility', methods=['GET'])
@jwt_required()
def get_admin_catalog_visibility():
    """Получить видимость каталогов (для админ-панели)"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        return jsonify({'success': True, 'visibility': _get_all_visibility()}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@catalog_visibility_bp.route('/admin-catalog-visibility', methods=['PUT'])
@jwt_required()
def update_catalog_visibility():
    """Обновить видимость одного каталога"""
    try:
        jwt_data = get_jwt()
        role = jwt_data.get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        data = request.get_json()
        catalog_type = data.get('type')
        enabled = data.get('enabled')

        if catalog_type not in VALID_TYPES:
            return jsonify({'error': f'Неверный тип каталога. Допустимые: {VALID_TYPES}'}), 400
        if not isinstance(enabled, bool):
            return jsonify({'error': 'Поле enabled должно быть булевым'}), 400

        record = CatalogVisibility.query.filter_by(catalog_type=catalog_type).first()
        if record:
            record.enabled = enabled
        else:
            record = CatalogVisibility(catalog_type=catalog_type, enabled=enabled)
            db.session.add(record)

        db.session.commit()

        return jsonify({'success': True, 'visibility': _get_all_visibility()}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
