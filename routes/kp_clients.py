"""
CRUD для адресной книги клиентов КП. Shared-пул на всех системных
пользователей: все видят всех, все могут править/удалять.

Удаление защищено: если хоть один `kp_history.client_id` ссылается на
этого клиента — возвращаем 409 с понятным текстом ошибки.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from extensions import db
from models.kp_client import KpClient
from models.kp_history import KPHistory

kp_clients_bp = Blueprint('kp_clients', __name__)


VALID_ORG_TYPES = {'too', 'ip', 'individual'}


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _validate_payload(data: dict, *, partial: bool = False) -> tuple[bool, str | None, dict]:
    """
    Валидация полей клиента в зависимости от типа организации.
    Возвращает (ok, error_message, normalized_data).

    `partial=True` — для PUT, разрешаем не передавать все поля (но если
    передан organization_type — проверяем согласованность).
    """
    org_type = (data.get('organization_type') or '').strip().lower()
    if not partial and org_type not in VALID_ORG_TYPES:
        return False, 'Тип организации обязателен (too / ip / individual)', {}
    if org_type and org_type not in VALID_ORG_TYPES:
        return False, f'Недопустимый тип организации: {org_type}', {}

    organization_name = (data.get('organization_name') or '').strip() or None
    full_name = (data.get('full_name') or '').strip() or None
    bin_ = (data.get('bin') or '').strip() or None
    iin = (data.get('iin') or '').strip() or None
    phone = (data.get('phone') or '').strip() or None
    whatsapp = (data.get('whatsapp') or '').strip() or None
    note = (data.get('note') or '').strip() or None

    if not partial:
        # Жёсткая валидация при создании
        if org_type == 'too':
            if not organization_name:
                return False, 'Для ТОО обязательно название организации', {}
            if not bin_:
                return False, 'Для ТОО обязателен БИН', {}
            if not full_name:
                return False, 'Для ТОО обязательно ФИО директора', {}
        elif org_type == 'ip':
            if not organization_name:
                return False, 'Для ИП обязательно название', {}
            if not iin:
                return False, 'Для ИП обязателен ИИН', {}
            if not full_name:
                return False, 'Для ИП обязательно ФИО директора/владельца', {}
        elif org_type == 'individual':
            if not full_name:
                return False, 'Для физ.лица обязательно ФИО', {}
            if not iin:
                return False, 'Для физ.лица обязателен ИИН', {}
            # organization_name для физлица игнорируем — даже если пришло
            organization_name = None
            bin_ = None

    return True, None, {
        'organization_type': org_type or None,
        'organization_name': organization_name,
        'full_name': full_name,
        'bin': bin_,
        'iin': iin,
        'phone': phone,
        'whatsapp': whatsapp,
        'note': note,
    }


@kp_clients_bp.route('/kp-clients', methods=['GET'])
@jwt_required()
def list_clients():
    err = _check_admin_role()
    if err:
        return err

    # Опциональный поиск по имени/ИИН/БИН/телефону для UI'шного фильтра
    q = (request.args.get('q') or '').strip()
    query = KpClient.query
    if q:
        like = f'%{q.lower()}%'
        query = query.filter(db.or_(
            db.func.lower(KpClient.organization_name).like(like),
            db.func.lower(KpClient.full_name).like(like),
            db.func.lower(KpClient.bin).like(like),
            db.func.lower(KpClient.iin).like(like),
            db.func.lower(KpClient.phone).like(like),
        ))

    clients = query.order_by(KpClient.organization_name, KpClient.full_name).all()
    return jsonify({
        'success': True,
        'clients': [c.to_dict() for c in clients],
    }), 200


@kp_clients_bp.route('/kp-clients/<int:client_id>', methods=['GET'])
@jwt_required()
def get_client(client_id):
    err = _check_admin_role()
    if err:
        return err
    client = KpClient.query.get(client_id)
    if not client:
        return jsonify({'error': 'Клиент не найден'}), 404
    return jsonify({'success': True, 'client': client.to_dict()}), 200


@kp_clients_bp.route('/kp-clients', methods=['POST'])
@jwt_required()
def create_client():
    err = _check_admin_role()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _validate_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    viewer_id = int(get_jwt_identity())
    client = KpClient(
        organization_type=fields['organization_type'],
        organization_name=fields['organization_name'],
        full_name=fields['full_name'],
        bin=fields['bin'],
        iin=fields['iin'],
        phone=fields['phone'],
        whatsapp=fields['whatsapp'],
        note=fields['note'],
        created_by=viewer_id,
    )
    db.session.add(client)
    db.session.commit()
    return jsonify({'success': True, 'client': client.to_dict()}), 201


@kp_clients_bp.route('/kp-clients/<int:client_id>', methods=['PUT'])
@jwt_required()
def update_client(client_id):
    err = _check_admin_role()
    if err:
        return err
    client = KpClient.query.get(client_id)
    if not client:
        return jsonify({'error': 'Клиент не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _validate_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    # Применяем только переданные поля. Для смены типа организации —
    # ре-валидируем уже обновлённый набор как для create.
    next_type = fields['organization_type'] or client.organization_type
    merged = {
        'organization_type': next_type,
        'organization_name': fields['organization_name'] if 'organization_name' in data else client.organization_name,
        'full_name': fields['full_name'] if 'full_name' in data else client.full_name,
        'bin': fields['bin'] if 'bin' in data else client.bin,
        'iin': fields['iin'] if 'iin' in data else client.iin,
        'phone': fields['phone'] if 'phone' in data else client.phone,
        'whatsapp': fields['whatsapp'] if 'whatsapp' in data else client.whatsapp,
        'note': fields['note'] if 'note' in data else client.note,
    }
    ok2, msg2, _ = _validate_payload(merged, partial=False)
    if not ok2:
        return jsonify({'error': msg2}), 400

    client.organization_type = merged['organization_type']
    client.organization_name = merged['organization_name']
    client.full_name = merged['full_name']
    client.bin = merged['bin']
    client.iin = merged['iin']
    client.phone = merged['phone']
    client.whatsapp = merged['whatsapp']
    client.note = merged['note']
    client.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'client': client.to_dict()}), 200


@kp_clients_bp.route('/kp-clients/<int:client_id>', methods=['DELETE'])
@jwt_required()
def delete_client(client_id):
    """
    Удаление клиента блокируется если на него ссылается хотя бы одна
    запись в kp_history — в любом КП любого менеджера. Иначе документ
    «потеряет» клиента, а это ценные данные.

    409 Conflict с количеством ссылающихся КП — UI покажет понятный текст.
    """
    err = _check_admin_role()
    if err:
        return err
    client = KpClient.query.get(client_id)
    if not client:
        return jsonify({'error': 'Клиент не найден'}), 404

    in_use_count = KPHistory.query.filter_by(client_id=client_id).count()
    if in_use_count > 0:
        return jsonify({
            'error': f'Нельзя удалить — клиент используется в {in_use_count} КП. '
                     f'Сначала отвяжите его от этих документов или удалите КП.',
            'in_use_count': in_use_count,
        }), 409

    db.session.delete(client)
    db.session.commit()
    return jsonify({'success': True}), 200
