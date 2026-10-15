"""
CRUD для адресной книги клиентов КП. Shared-пул на всех системных
пользователей: все видят всех, все могут править/удалять.

Удаление защищено: если хоть один `kp_history.client_id` ссылается на
этого клиента — возвращаем 409 с понятным текстом ошибки.

С 2026-06-XX схема упрощена: ФИО + Объект (текст) + Контакты (массив
телефонов с заметками). Старые поля (organization_type/bin/iin/whatsapp/
note/organization_name) выпилены — миграция в `app.py` переносит phone
и whatsapp в contacts, остальное теряется.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from extensions import db
from models.kp_client import KpClient
from models.kp_history import KPHistory

kp_clients_bp = Blueprint('kp_clients', __name__)


def _check_admin_role():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _normalize_contacts(raw) -> tuple[bool, str | None, list]:
    """
    Валидация массива контактов. Возвращает (ok, error, normalized).
    Каждый элемент должен быть dict-ом с непустым `phone`. `note` опц.
    Записи с пустым phone после strip — выкидываем.
    """
    if raw is None:
        return True, None, []
    if not isinstance(raw, list):
        return False, 'Контакты должны быть массивом', []
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return False, f'Контакт #{i + 1} должен быть объектом', []
        phone = (item.get('phone') or '').strip()
        note = (item.get('note') or '').strip()
        if not phone:
            # Пустые контакты игнорируем — их можно нажать «Добавить» и не
            # заполнить, ничего страшного.
            continue
        out.append({'phone': phone, 'note': note})
    return True, None, out


def _validate_payload(data: dict, *, partial: bool = False) -> tuple[bool, str | None, dict]:
    """
    Валидация payload-а клиента. Поля: full_name (обязателен при create),
    object (опц), contacts (массив).
    """
    full_name = (data.get('full_name') or '').strip() or None
    object_ = (data.get('object') or '').strip() or None

    if not partial and not full_name:
        return False, 'ФИО клиента обязательно', {}

    contacts_present = 'contacts' in data
    if contacts_present:
        ok, msg, contacts = _normalize_contacts(data.get('contacts'))
        if not ok:
            return False, msg, {}
    else:
        contacts = None  # сигнал «не обновлять» для PUT

    return True, None, {
        'full_name': full_name,
        'object': object_,
        'contacts': contacts,
    }


@kp_clients_bp.route('/kp-clients', methods=['GET'])
@jwt_required()
def list_clients():
    err = _check_admin_role()
    if err:
        return err

    # Опциональный поиск по ФИО / объекту. По contacts JSONB не ищем —
    # списки на бэке короткие, фронт всё равно фильтрует уже отрисованное.
    q = (request.args.get('q') or '').strip()
    with_counts = request.args.get('with_counts') == '1'

    query = KpClient.query
    if q:
        like = f'%{q.lower()}%'
        query = query.filter(db.or_(
            db.func.lower(KpClient.full_name).like(like),
            db.func.lower(KpClient.object).like(like),
        ))

    clients = query.order_by(KpClient.full_name).all()

    out = [c.to_dict() for c in clients]

    # Автор клиента — батч-резолв в имя (чтобы фронт мог рендерить
    # «Кем создан» и фильтр без второго запроса в system-users).
    creator_ids = {c.created_by for c in clients if c.created_by}
    if creator_ids:
        from models.systemuser import SystemUser
        creators = {
            u.id: {
                'id': u.id,
                'name': u.full_name or u.email,
                'email': u.email,
            }
            for u in SystemUser.query.filter(SystemUser.id.in_(creator_ids)).all()
        }
        for row in out:
            cb = row.get('created_by')
            row['creator'] = creators.get(cb) if cb else None
    else:
        for row in out:
            row['creator'] = None

    if with_counts and clients:
        # Батч-подсчёт где именно используется клиент: КП / сделки / задачи.
        # Три GROUP BY — не N+1, одним SQL-запросом каждый.
        from models.deal import Deal
        from models.task import Task
        ids = [c.id for c in clients]
        kp_counts = dict(db.session.query(
            KPHistory.client_id, db.func.count(KPHistory.id),
        ).filter(KPHistory.client_id.in_(ids)).group_by(KPHistory.client_id).all())
        deal_counts = dict(db.session.query(
            Deal.client_id, db.func.count(Deal.id),
        ).filter(Deal.client_id.in_(ids)).group_by(Deal.client_id).all())
        task_counts = dict(db.session.query(
            Task.client_id, db.func.count(Task.id),
        ).filter(Task.client_id.in_(ids)).group_by(Task.client_id).all())
        for row in out:
            cid = row['id']
            row['kp_count'] = int(kp_counts.get(cid, 0))
            row['deal_count'] = int(deal_counts.get(cid, 0))
            row['task_count'] = int(task_counts.get(cid, 0))

    return jsonify({
        'success': True,
        'clients': out,
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
        full_name=fields['full_name'],
        object=fields['object'],
        contacts=fields['contacts'] or [],
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

    # Применяем только переданные поля. Для full_name пустая строка
    # тоже считается «не передано» — клиент не может остаться без ФИО.
    if fields['full_name'] is not None:
        client.full_name = fields['full_name']
    if 'object' in data:
        client.object = fields['object']
    if fields['contacts'] is not None:
        client.contacts = fields['contacts']

    if not client.full_name:
        return jsonify({'error': 'ФИО клиента обязательно'}), 400

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

    # Проверяем ссылки из КП, сделок, задач. Если есть хоть где — блокируем,
    # чтобы не осиротить документы (данные клиента + история общения ценные).
    from models.deal import Deal
    from models.task import Task
    kp_cnt = KPHistory.query.filter_by(client_id=client_id).count()
    deal_cnt = Deal.query.filter_by(client_id=client_id).count()
    task_cnt = Task.query.filter_by(client_id=client_id).count()
    total = kp_cnt + deal_cnt + task_cnt
    if total > 0:
        parts = []
        if kp_cnt: parts.append(f'{kp_cnt} КП')
        if deal_cnt: parts.append(f'{deal_cnt} сделок')
        if task_cnt: parts.append(f'{task_cnt} задач')
        return jsonify({
            'error': f'Нельзя удалить — клиент используется в: {", ".join(parts)}. '
                     f'Сначала отвяжите его.',
            'in_use_count': total,
            'kp_count': kp_cnt,
            'deal_count': deal_cnt,
            'task_count': task_cnt,
        }), 409

    db.session.delete(client)
    db.session.commit()
    return jsonify({'success': True}), 200
