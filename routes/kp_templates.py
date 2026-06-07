"""
CRUD для шаблонов КП. Shared-пул на всех системных пользователей: все
видят все, все могут править/удалять. Идея — «фирменный бланк»: один
раз настроили лого/колонки/текст шапки/колонтитул — потом любой менеджер
импортирует это в свои настройки одним кликом.

Импорт делается полностью на фронте (replace локального kpSettings) —
бэку про это знать не нужно. Шаблон при импорте не меняется (read-only
для этой операции).
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from extensions import db
from models.kp_template import KpTemplate

kp_templates_bp = Blueprint('kp_templates', __name__)


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _validate_payload(data: dict, *, partial: bool = False):
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip() or None
    settings = data.get('settings')

    if not partial:
        if not name:
            return False, 'Название шаблона обязательно', None
        if not isinstance(settings, dict):
            return False, 'settings должно быть объектом', None
    else:
        if 'name' in data and not name:
            return False, 'Название шаблона не может быть пустым', None
        if 'settings' in data and not isinstance(settings, dict):
            return False, 'settings должно быть объектом', None

    return True, None, {
        'name': name if name else None,
        'description': description,
        'settings': settings,
    }


@kp_templates_bp.route('/kp-templates', methods=['GET'])
@jwt_required()
def list_templates():
    err = _check_admin_role()
    if err:
        return err
    items = KpTemplate.query.order_by(KpTemplate.updated_at.desc()).all()
    return jsonify({'success': True, 'templates': [t.to_dict() for t in items]}), 200


@kp_templates_bp.route('/kp-templates/<int:template_id>', methods=['GET'])
@jwt_required()
def get_template(template_id):
    err = _check_admin_role()
    if err:
        return err
    tpl = KpTemplate.query.get(template_id)
    if not tpl:
        return jsonify({'error': 'Шаблон не найден'}), 404
    return jsonify({'success': True, 'template': tpl.to_dict()}), 200


@kp_templates_bp.route('/kp-templates', methods=['POST'])
@jwt_required()
def create_template():
    err = _check_admin_role()
    if err:
        return err
    data = request.get_json() or {}
    ok, msg, fields = _validate_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    viewer_id = int(get_jwt_identity())
    tpl = KpTemplate(
        name=fields['name'],
        description=fields['description'],
        settings=fields['settings'],
        created_by=viewer_id,
    )
    db.session.add(tpl)
    db.session.commit()
    return jsonify({'success': True, 'template': tpl.to_dict()}), 201


@kp_templates_bp.route('/kp-templates/<int:template_id>', methods=['PUT'])
@jwt_required()
def update_template(template_id):
    err = _check_admin_role()
    if err:
        return err
    tpl = KpTemplate.query.get(template_id)
    if not tpl:
        return jsonify({'error': 'Шаблон не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _validate_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in data and fields['name']:
        tpl.name = fields['name']
    if 'description' in data:
        tpl.description = fields['description']
    if 'settings' in data:
        tpl.settings = fields['settings']

    tpl.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'template': tpl.to_dict()}), 200


@kp_templates_bp.route('/kp-templates/<int:template_id>', methods=['DELETE'])
@jwt_required()
def delete_template(template_id):
    err = _check_admin_role()
    if err:
        return err
    tpl = KpTemplate.query.get(template_id)
    if not tpl:
        return jsonify({'error': 'Шаблон не найден'}), 404
    db.session.delete(tpl)
    db.session.commit()
    return jsonify({'success': True}), 200
