from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy import or_

from extensions import db
from models.kp_history import KPHistory
from models.kp_share import KPShare
from models.systemuser import SystemUser
from routes.kp_share import is_super_admin, kp_access_level, can_share_kp

kp_history_bp = Blueprint('kp_history', __name__)


def _enrich_for_response(record: KPHistory, viewer_id: int, access: str, *, short: bool):
    """
    Дополняет ответ полями, нужными UI: `access_level`, владелец КП,
    `is_shared` (true если viewer не владелец, но имеет доступ).
    """
    base = record.to_dict(short=short)
    base['user_id'] = record.user_id
    base['access_level'] = access  # 'owner' | 'edit' | 'view'
    if record.user_id != viewer_id:
        base['shared_by_user_id'] = record.user_id
        # Денормализуем имя владельца — нужно для бейджа «Поделено · от X»
        owner = SystemUser.query.get(record.user_id)
        base['shared_by'] = {
            'id': owner.id,
            'email': owner.email,
            'full_name': owner.full_name,
        } if owner else None
    return base


@kp_history_bp.route('/kp-history', methods=['GET'])
@jwt_required()
def get_kp_history_list():
    """
    Список КП с учётом шаринга и super-admin прав.

    Query params:
      ?filter=mine    — только свои (default)
      ?filter=shared  — только реально расшаренные мне через KPShare. Для
                         super-admin'а трактуется так же как для обычного:
                         «расшарил» = кто-то явно передал доступ через UI
                         «Поделиться». Привилегии видеть всё — отдельный
                         пункт `all`, не путать.
      ?filter=all     — все КП всех пользователей. Только для super-admin/owner.
      ?filter=user&user_id=N — все КП конкретного юзера. Только super-admin.
    Без фильтра super-admin/owner получает все, обычный юзер — свои + расшаренные.
    """
    try:
        viewer_id = int(get_jwt_identity())
        role = (get_jwt() or {}).get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        viewer_super = is_super_admin(viewer_id)
        flt = (request.args.get('filter') or '').strip().lower()

        if flt == 'mine':
            records = (KPHistory.query
                       .filter_by(user_id=viewer_id)
                       .order_by(KPHistory.created_at.desc())
                       .all())
        elif flt == 'shared':
            # Только КП, на которые есть запись в KPShare для этого юзера —
            # одинаково для super-admin'а и обычного юзера.
            shared_ids = [s.kp_history_id for s in KPShare.query.filter_by(
                shared_with_user_id=viewer_id).all()]
            if not shared_ids:
                records = []
            else:
                records = (KPHistory.query
                           .filter(KPHistory.id.in_(shared_ids))
                           .order_by(KPHistory.created_at.desc())
                           .all())
        elif flt == 'all':
            # Все КП в системе. Доступно только super-admin/owner.
            if not viewer_super:
                return jsonify({'error': 'Доступ запрещён'}), 403
            records = (KPHistory.query
                       .order_by(KPHistory.created_at.desc())
                       .all())
        elif flt == 'user':
            if not viewer_super:
                return jsonify({'error': 'Только super-admin может фильтровать по пользователю'}), 403
            try:
                target_uid = int(request.args.get('user_id') or 0)
            except (ValueError, TypeError):
                target_uid = 0
            if target_uid <= 0:
                return jsonify({'error': 'user_id обязателен'}), 400
            records = (KPHistory.query
                       .filter_by(user_id=target_uid)
                       .order_by(KPHistory.created_at.desc())
                       .all())
        else:
            # Без фильтра
            if viewer_super:
                records = (KPHistory.query
                           .order_by(KPHistory.created_at.desc())
                           .all())
            else:
                shared_ids = [s.kp_history_id for s in KPShare.query.filter_by(
                    shared_with_user_id=viewer_id).all()]
                q = KPHistory.query.filter(
                    or_(
                        KPHistory.user_id == viewer_id,
                        KPHistory.id.in_(shared_ids) if shared_ids else False,
                    )
                )
                records = q.order_by(KPHistory.created_at.desc()).all()

        history = []
        for r in records:
            access = kp_access_level(viewer_id, r) or 'view'
            history.append(_enrich_for_response(r, viewer_id, access, short=True))

        # «Есть ли вообще что-то доступное помимо собственных» — UI на этом
        # решает показывать ли онбординг-карточку «Список КП пуст». Если
        # юзеру что-то расшарили (или он super-admin и в системе есть чужие
        # КП) — онбординг не нужен, должны быть видны фильтр и колонки.
        if viewer_super:
            has_other_visible = (
                KPHistory.query.filter(KPHistory.user_id != viewer_id).first() is not None
            )
        else:
            has_other_visible = (
                KPShare.query.filter_by(shared_with_user_id=viewer_id).first() is not None
            )

        return jsonify({
            'success': True,
            'history': history,
            'is_super_admin': viewer_super,
            'has_other_visible': has_other_visible,
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history/<int:history_id>', methods=['GET'])
@jwt_required()
def get_kp_history_item(history_id):
    """Полные данные одного КП — если viewer имеет хоть какой-то доступ."""
    try:
        viewer_id = int(get_jwt_identity())
        role = (get_jwt() or {}).get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPHistory.query.get(history_id)
        if not record:
            return jsonify({'error': 'КП не найдено'}), 404

        access = kp_access_level(viewer_id, record)
        if access is None:
            return jsonify({'error': 'КП не найдено'}), 404

        return jsonify({
            'success': True,
            'data': _enrich_for_response(record, viewer_id, access, short=False),
            'can_share': can_share_kp(viewer_id, record),
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history', methods=['POST'])
@jwt_required()
def save_kp_history():
    """Сохранить КП в историю — всегда от имени текущего пользователя."""
    try:
        user_id = int(get_jwt_identity())
        role = (get_jwt() or {}).get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        name = data.get('name', '').strip() or 'КП без названия'
        items = data.get('items', [])
        settings = data.get('settings', {})
        total_amount = data.get('total_amount', 0)
        calculator_data = data.get('calculator_data', None)
        # client_id — опциональная привязка к адресной книге. None = без клиента.
        # Если передан несуществующий id — пишем None (не падаем 500).
        client_id_raw = data.get('client_id')
        client_id = None
        if client_id_raw not in (None, '', 0, '0'):
            try:
                from models.kp_client import KpClient
                cid = int(client_id_raw)
                if KpClient.query.get(cid):
                    client_id = cid
            except (ValueError, TypeError):
                pass

        record = KPHistory(
            user_id=user_id,
            user_role=role,
            name=name,
            items=items,
            settings=settings,
            total_amount=total_amount,
            calculator_data=calculator_data,
            client_id=client_id,
        )
        db.session.add(record)
        db.session.commit()

        return jsonify({
            'success': True,
            'id': record.id,
            'message': 'КП сохранено в историю'
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history/<int:history_id>', methods=['PUT'])
@jwt_required()
def update_kp_history(history_id):
    """
    Обновить КП. Доступно владельцу, super-admin'у и тем, кому расшарили
    с access_level='edit'. Тем кому расшарили 'view' — 403.
    """
    try:
        viewer_id = int(get_jwt_identity())
        role = (get_jwt() or {}).get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPHistory.query.get(history_id)
        if not record:
            return jsonify({'error': 'КП не найдено'}), 404

        access = kp_access_level(viewer_id, record)
        if access is None:
            return jsonify({'error': 'КП не найдено'}), 404
        if access == 'view':
            return jsonify({'error': 'У вас доступ только на просмотр'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        if 'name' in data:
            record.name = data['name'].strip() or record.name
        if 'items' in data:
            record.items = data['items']
        if 'settings' in data:
            record.settings = data['settings']
        if 'total_amount' in data:
            record.total_amount = data['total_amount']
        if 'calculator_data' in data:
            record.calculator_data = data['calculator_data']
        if 'client_id' in data:
            v = data['client_id']
            if v in (None, '', 0, '0'):
                record.client_id = None
            else:
                try:
                    from models.kp_client import KpClient
                    cid = int(v)
                    if KpClient.query.get(cid):
                        record.client_id = cid
                except (ValueError, TypeError):
                    pass
        # Подписать / разподписать контракт. Доступно при edit-доступе.
        if 'signed_at' in data:
            v = data['signed_at']
            if v is None:
                record.signed_at = None
            elif v == 'now':
                record.signed_at = datetime.utcnow()
            else:
                try:
                    record.signed_at = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    return jsonify({'error': 'signed_at должен быть ISO-датой, "now" или null'}), 400

        db.session.commit()

        return jsonify({
            'success': True,
            'id': record.id,
            'message': 'КП обновлено'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@kp_history_bp.route('/kp-history/<int:history_id>', methods=['DELETE'])
@jwt_required()
def delete_kp_history(history_id):
    """
    Удалить КП. По требованию — только владелец КП (создатель). Даже
    super-admin/owner не могут удалять чужие КП через UI, чтобы случайно
    не уничтожить чужую работу. Сами шары удалятся каскадом из-за FK.
    """
    try:
        viewer_id = int(get_jwt_identity())
        role = (get_jwt() or {}).get('role', 'client')
        if role not in ('admin', 'system'):
            return jsonify({'error': 'Доступ запрещён'}), 403

        record = KPHistory.query.get(history_id)
        if not record:
            return jsonify({'error': 'КП не найдено'}), 404
        if record.user_id != viewer_id:
            return jsonify({'error': 'Удалить КП может только его владелец'}), 403

        db.session.delete(record)
        db.session.commit()
        return jsonify({'success': True, 'message': 'КП удалено'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
