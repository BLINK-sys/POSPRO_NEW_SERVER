"""
CRUD сделок CRM + M2M-связи (участники, КП, заказы) + move-stage.

Access matrix:
  admin       — видит и правит ВСЕ сделки; может назначать/перекидывать
                ответственного, удалять чужие сделки.
  system      — видит только свои: где responsible_user_id = я ИЛИ я
                участник (deal_member). Правит свои (responsible=me)
                и те где я participant. Наблюдатель (observer) — read-only.

Endpoints:
  GET    /api/admin/deals                       список с фильтрами и пагинацией
  POST   /api/admin/deals                       создать
  GET    /api/admin/deals/<id>                  детали (+ activity, KP, orders, members)
  PUT    /api/admin/deals/<id>                  обновить (все редактируемые поля)
  DELETE /api/admin/deals/<id>                  удалить
  POST   /api/admin/deals/<id>/move             сменить стадию (drag Kanban)

  POST   /api/admin/deals/<id>/members          пригласить участника/наблюдателя
  DELETE /api/admin/deals/<id>/members/<uid>    убрать участника

  POST   /api/admin/deals/<id>/kp               прикрепить КП (payload: kp_history_id)
  DELETE /api/admin/deals/<id>/kp/<kid>         открепить

  POST   /api/admin/deals/<id>/orders           привязать заказ
  DELETE /api/admin/deals/<id>/orders/<oid>     отвязать

  GET    /api/admin/deals/<id>/activity         лента событий (сериал через
                                                deal_activity; используется во
                                                вкладке «Лента» карточки сделки)

Move-stage делает ДВЕ вещи:
  1) Обновляет stage_id (и meta-логика: если стадия типа `won`/`lost` —
     статус сделки автоматически становится 'won'/'lost'; если normal —
     возвращается в 'open').
  2) Пишет `deal_activity` с kind='stage_changed' и payload'ом
     {from_stage_id, to_stage_id}.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from sqlalchemy import or_, and_

from extensions import db
from models.deal import (
    Deal, DealMember, DealKp, DealOrder, DealActivity,
    DEAL_PRIORITIES, DEAL_SOURCES, DEAL_STATUSES,
    DEAL_MEMBER_ROLES,
)
from models.deal_pipeline import DealPipeline, DealStage
from models.systemuser import SystemUser
from models.kp_client import KpClient
from models.kp_history import KPHistory
from models.order import Order


deals_bp = Blueprint('deals', __name__)


def _safe_notify(**kwargs):
    """
    Best-effort вызов notify() — сбой не валит основной путь. Импорт
    отложенный (в момент вызова), чтобы избежать циркулярной зависимости
    services→models при загрузке приложения.

    Внутренний notify() только flush'ит запись, но НЕ коммитит. Мы
    коммитим тут — иначе Notification останется в открытой транзакции,
    и SSE-стрим её не увидит (звука/бейджа у получателя не будет).
    """
    try:
        from services.notifications import notify
        notify(**kwargs)
        db.session.commit()
    except Exception as e:
        print(f'⚠️ notify failed: {e}', flush=True)


# ============================================================================
# Auth helpers
# ============================================================================

def _current_role_and_id() -> tuple[str | None, int | None]:
    claims = get_jwt() or {}
    role = claims.get('role')
    try:
        uid = int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        uid = None
    return role, uid


def _check_admin_or_system():
    role, _ = _current_role_and_id()
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _visible_deals_query(role: str, user_id: int | None):
    """
    Правила видимости:
      - owner (is_owner=True) → все сделки.
      - обычный SystemUser с can_see_all_deals=True → все сделки.
      - остальные SystemUser → creator=me OR responsible=me OR я в DealMember.

    Роль в JWT (role='admin' у всех SystemUser) больше не даёт полный
    список — специальные права живут в БД в system_users. См. services/perms.
    """
    from services.perms import can_see_all_deals as _cs
    q = Deal.query
    if not user_id:
        return q.filter(db.text('1=0'))
    if _cs(user_id):
        return q
    q = q.outerjoin(
        DealMember,
        and_(DealMember.deal_id == Deal.id, DealMember.user_id == user_id),
    ).filter(or_(
        Deal.creator_id == user_id,
        Deal.responsible_user_id == user_id,
        DealMember.id.isnot(None),
    )).distinct()
    return q


def _can_edit_deal(deal: Deal, role: str, user_id: int | None) -> bool:
    """
    owner — правит любую сделку.
    can_see_all_deals — тоже правит любую (флаг «полный доступ ко всем сделкам»).
    остальные — правят если я creator, responsible, или участник
    (participant, не observer).
    """
    from services.perms import is_owner as _is_owner, can_see_all_deals as _cs
    if not user_id:
        return False
    if _cs(user_id):  # включает is_owner
        return True
    if deal.creator_id == user_id:
        return True
    if deal.responsible_user_id == user_id:
        return True
    member = DealMember.query.filter_by(deal_id=deal.id, user_id=user_id).first()
    return bool(member and member.role == 'participant')


# ============================================================================
# Serialization
# ============================================================================

def _deal_full_dict(deal: Deal) -> dict:
    """
    Развёрнутое представление сделки: сама сделка + связи + денормализованные
    данные КП и заказов (name/amount/created_at) — чтобы фронт не делал
    N+1 запросов при рендере вкладок.
    """
    d = deal.to_dict()

    # Members с ролями.
    members = DealMember.query.filter_by(deal_id=deal.id).all()
    d['members'] = [
        {'id': m.id, 'user_id': m.user_id, 'role': m.role,
         'added_at': m.added_at.isoformat() if m.added_at else None}
        for m in members
    ]

    # Прикреплённые КП — с денормализованным именем и суммой из kp_history.
    kps = (
        db.session.query(DealKp, KPHistory)
        .join(KPHistory, KPHistory.id == DealKp.kp_history_id)
        .filter(DealKp.deal_id == deal.id)
        .all()
    )
    d['kps'] = [
        {
            'id': k.id, 'kp_history_id': k.kp_history_id,
            'attached_at': k.attached_at.isoformat() if k.attached_at else None,
            'attached_by': k.attached_by,
            'kp': {
                'id': kp.id,
                'name': kp.name,
                'total_amount': float(kp.total_amount or 0),
                'signed_at': kp.signed_at.isoformat() if kp.signed_at else None,
                'created_at': kp.created_at.isoformat() if kp.created_at else None,
            },
        }
        for k, kp in kps
    ]

    # Привязанные заказы — с денормализованным номером/суммой/клиентом.
    orders = (
        db.session.query(DealOrder, Order)
        .join(Order, Order.id == DealOrder.order_id)
        .filter(DealOrder.deal_id == deal.id)
        .all()
    )
    d['orders'] = [
        {
            'id': o.id, 'order_id': o.order_id,
            'attached_at': o.attached_at.isoformat() if o.attached_at else None,
            'order': {
                'id': order.id,
                'order_number': order.order_number,
                'total_amount': float(order.total_amount or 0),
                'customer_name': order.customer_name,
                'payment_status': order.payment_status,
                'created_at': order.created_at.isoformat() if order.created_at else None,
            },
        }
        for o, order in orders
    ]

    # Разворачиваем источник сделки (DealSource) — название + цвет для чипа.
    d['deal_source'] = None
    d['source_variant'] = None
    if deal.source_id:
        try:
            from models.deal_source import DealSource, DealSourceVariant
            ds = DealSource.query.get(deal.source_id)
            if ds:
                d['deal_source'] = {
                    'id': ds.id,
                    'name': ds.name,
                    'color': ds.color,
                }
            if deal.source_variant_id:
                dv = DealSourceVariant.query.get(deal.source_variant_id)
                if dv and dv.parent_source_id == deal.source_id:
                    d['source_variant'] = {
                        'id': dv.id,
                        'parent_source_id': dv.parent_source_id,
                        'name': dv.name,
                    }
        except Exception:
            pass

    # Компания (`kp_company`) и мультисвязь контактов — JOIN одной выборкой.
    d['company'] = None
    if deal.company_id:
        try:
            from models.kp_company import KpCompany
            co = KpCompany.query.get(deal.company_id)
            if co:
                d['company'] = {
                    'id': co.id,
                    'name': co.name,
                    'bin': co.bin,
                    'phone': co.phone,
                }
        except Exception:
            pass

    d['contacts'] = []
    try:
        from models.kp_company import DealContact
        from models.kp_client import KpClient
        rows = (
            db.session.query(DealContact, KpClient)
            .join(KpClient, KpClient.id == DealContact.client_id)
            .filter(DealContact.deal_id == deal.id)
            .order_by(DealContact.is_primary.desc(), DealContact.added_at.asc())
            .all()
        )
        d['contacts'] = [
            {
                'client_id': cl.id,
                'name': cl.display_name,
                'is_primary': bool(dc.is_primary),
                'contacts': cl.contacts or [],
                'company_id': cl.company_id,
            }
            for dc, cl in rows
        ]
    except Exception:
        pass

    # Название источника ingest'а (для метки на карточке). Одиночный
    # deal — точечно ищем правило, не тянем всю таблицу.
    d['source_name'] = None
    if deal.source_ref_type:
        try:
            from models.crm_ingest_source import CrmIngestSource
            if deal.source_ref_type.startswith('webhook:'):
                prefix = deal.source_ref_type.split(':', 1)[1]
                for s in CrmIngestSource.query.filter(
                    CrmIngestSource.token.isnot(None),
                ).all():
                    if s.token and s.token.startswith(prefix):
                        d['source_name'] = s.name
                        break
            else:
                s = CrmIngestSource.query.filter_by(
                    source_key=deal.source_ref_type,
                ).first()
                if s:
                    d['source_name'] = s.name
        except Exception:
            pass

    return d


# ============================================================================
# Валидация
# ============================================================================

def _validate_source_variant_pair(source_id, source_variant_id):
    """
    Проверяет что source_variant (если указан) принадлежит выбранному
    родителю. Возвращает (jsonify, 400) при ошибке, None если ок.
    """
    if not source_variant_id:
        return None
    if not source_id:
        return jsonify({
            'error': 'Для выбора «Доп. источника» надо сначала выбрать источник',
        }), 400
    try:
        from models.deal_source import DealSourceVariant
        v = DealSourceVariant.query.get(int(source_variant_id))
    except Exception:
        v = None
    if not v:
        return jsonify({'error': 'Доп. источник не найден'}), 400
    if v.parent_source_id != int(source_id):
        return jsonify({
            'error': 'Доп. источник не принадлежит выбранному источнику',
        }), 400
    return None


def _parse_deal_payload(data: dict, *, partial: bool = False):
    """Валидация тела POST/PUT /deals."""
    fields = {}

    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название сделки обязательно', {}
    if name is not None:
        fields['name'] = name

    if not partial:
        # Обязательные при создании
        for k in ('pipeline_id', 'stage_id'):
            try:
                fields[k] = int(data[k])
            except (TypeError, ValueError, KeyError):
                return False, f'{k} обязателен', {}

    # Опциональные для PUT/POST.
    for k in ('pipeline_id', 'stage_id', 'client_id', 'company_id', 'responsible_user_id'):
        if k in data and data[k] is not None and k not in fields:
            try:
                fields[k] = int(data[k])
            except (TypeError, ValueError):
                return False, f'{k} должен быть числом', {}
        elif k in data and data[k] is None:
            fields[k] = None  # явное «сбросить»

    # contact_ids: [int, …] — список привязанных контактов сделки.
    # primary_contact_id — какой из них «основной» (dedup `deal.client_id`).
    # Если передан contact_ids без primary — primary = первый из списка.
    if 'contact_ids' in data:
        raw = data.get('contact_ids') or []
        if not isinstance(raw, list):
            return False, 'contact_ids должен быть массивом', {}
        try:
            ids = [int(x) for x in raw if x is not None]
        except (TypeError, ValueError):
            return False, 'contact_ids должен содержать числа', {}
        # dedup с сохранением порядка
        seen = set()
        clean: list[int] = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                clean.append(x)
        fields['contact_ids'] = clean

    if 'primary_contact_id' in data:
        v = data.get('primary_contact_id')
        if v in (None, '', 0):
            fields['primary_contact_id'] = None
        else:
            try:
                fields['primary_contact_id'] = int(v)
            except (TypeError, ValueError):
                return False, 'primary_contact_id должен быть числом', {}

    if 'amount' in data:
        v = data['amount']
        if v is None or v == '':
            fields['amount'] = None
        else:
            try:
                fields['amount'] = float(v)
            except (TypeError, ValueError):
                return False, 'amount должен быть числом', {}
    if 'currency' in data:
        cur = (data.get('currency') or '').strip() or None
        if cur:
            fields['currency'] = cur

    if 'priority' in data:
        p = data.get('priority')
        if p and p not in DEAL_PRIORITIES:
            return False, f'priority: {", ".join(DEAL_PRIORITIES)}', {}
        if p:
            fields['priority'] = p

    if 'source' in data:
        s = data.get('source')
        if s and s not in DEAL_SOURCES:
            return False, f'source: {", ".join(DEAL_SOURCES)}', {}
        fields['source'] = s or None

    if 'source_id' in data:
        sid = data.get('source_id')
        if sid in (None, '', 0):
            fields['source_id'] = None
        else:
            try:
                fields['source_id'] = int(sid)
            except (TypeError, ValueError):
                return False, 'source_id должен быть числом', {}

    if 'source_variant_id' in data:
        vid = data.get('source_variant_id')
        if vid in (None, '', 0):
            fields['source_variant_id'] = None
        else:
            try:
                fields['source_variant_id'] = int(vid)
            except (TypeError, ValueError):
                return False, 'source_variant_id должен быть числом', {}

    if 'status' in data:
        st = data.get('status')
        if st and st not in DEAL_STATUSES:
            return False, f'status: {", ".join(DEAL_STATUSES)}', {}
        if st:
            fields['status'] = st

    if 'expected_close_at' in data:
        v = data.get('expected_close_at')
        if v:
            try:
                fields['expected_close_at'] = datetime.fromisoformat(v.replace('Z', '+00:00'))
            except (TypeError, ValueError):
                return False, 'expected_close_at должен быть ISO8601', {}
        else:
            fields['expected_close_at'] = None

    if 'tags' in data:
        tags = data.get('tags') or []
        if not isinstance(tags, list):
            return False, 'tags должны быть массивом', {}
        fields['tags'] = tags

    if 'notes' in data:
        fields['notes'] = data.get('notes') or None

    return True, None, fields


# ============================================================================
# List / Get / Create / Update / Delete
# ============================================================================

@deals_bp.route('/admin/deals', methods=['GET'])
@jwt_required()
def list_deals():
    """
    Список сделок с фильтрами и пагинацией.

    Query params:
      pipeline_id     — фильтр по воронке
      stage_id        — фильтр по стадии (обычно нужен только для list-view,
                        для Kanban фронт получает все стадии сразу)
      status          — open / won / lost
      responsible_id  — все сделки этого менеджера
      mine=1          — только мои (переопределяет responsible_id)
      q               — поиск по name / notes
      limit / offset  — пагинация (по умолчанию 50/0)

    admin видит всё, system — только свои (по правилам _visible_deals_query).
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    q = _visible_deals_query(role, user_id)

    pipeline_id = request.args.get('pipeline_id', type=int)
    stage_id = request.args.get('stage_id', type=int)
    status = request.args.get('status')
    responsible_id_raw = request.args.get('responsible_id')
    # 'none' → фильтр «Без ответственного» (responsible_user_id IS NULL),
    # число → конкретный юзер, иначе — не фильтруем.
    responsible_none = responsible_id_raw == 'none'
    try:
        responsible_id = int(responsible_id_raw) if responsible_id_raw and not responsible_none else None
    except (TypeError, ValueError):
        responsible_id = None
    client_id = request.args.get('client_id', type=int)
    company_id = request.args.get('company_id', type=int)
    mine = request.args.get('mine') == '1'
    search = (request.args.get('q') or '').strip()

    # created_after/created_before: ISO date (YYYY-MM-DD) или ISO datetime.
    # Используется для фильтра «период» на канбане (default 3 мес).
    def _parse_iso(v):
        if not v:
            return None
        try:
            return datetime.fromisoformat(v.replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None
    created_after = _parse_iso(request.args.get('created_after'))
    created_before = _parse_iso(request.args.get('created_before'))

    if pipeline_id:
        q = q.filter(Deal.pipeline_id == pipeline_id)
    if stage_id:
        q = q.filter(Deal.stage_id == stage_id)
    if status in DEAL_STATUSES:
        q = q.filter(Deal.status == status)
    if mine and user_id:
        q = q.filter(Deal.responsible_user_id == user_id)
    elif responsible_none:
        q = q.filter(Deal.responsible_user_id.is_(None))
    elif responsible_id:
        q = q.filter(Deal.responsible_user_id == responsible_id)
    if client_id:
        # Сделки где client_id = primary ИЛИ где этот клиент в DealContact
        # (мульти-привязка). Через subquery чтобы не дёргать join дважды.
        from models.kp_company import DealContact
        contact_deal_ids = db.session.query(DealContact.deal_id).filter(
            DealContact.client_id == client_id,
        ).subquery()
        q = q.filter(or_(
            Deal.client_id == client_id,
            Deal.id.in_(contact_deal_ids),
        ))
    if company_id:
        q = q.filter(Deal.company_id == company_id)
    # Фильтр по источнику: 'none' → без источника, int → конкретный.
    source_id = request.args.get('source_id')
    if source_id == 'none':
        q = q.filter(Deal.source_id.is_(None))
    elif source_id:
        try:
            q = q.filter(Deal.source_id == int(source_id))
        except (TypeError, ValueError):
            pass
    # Фильтр по доп. источнику (variant): 'none' → без варианта, int → конкретный.
    source_variant_id = request.args.get('source_variant_id')
    if source_variant_id == 'none':
        q = q.filter(Deal.source_variant_id.is_(None))
    elif source_variant_id:
        try:
            q = q.filter(Deal.source_variant_id == int(source_variant_id))
        except (TypeError, ValueError):
            pass
    # Диапазон суммы — для фильтра на /admin/deals/history.
    amount_min = request.args.get('amount_min', type=float)
    amount_max = request.args.get('amount_max', type=float)
    if amount_min is not None:
        q = q.filter(Deal.amount >= amount_min)
    if amount_max is not None:
        q = q.filter(Deal.amount <= amount_max)
    if created_after:
        q = q.filter(Deal.created_at >= created_after)
    if created_before:
        q = q.filter(Deal.created_at <= created_before)
    if search:
        like = f'%{search.lower()}%'
        q = q.filter(or_(
            db.func.lower(Deal.name).like(like),
            db.func.lower(db.func.coalesce(Deal.notes, '')).like(like),
        ))

    total = q.count()
    limit = min(request.args.get('limit', 50, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)

    # ORDER BY created_at DESC: канбан показывает свежие сделки сверху.
    deals = q.order_by(Deal.created_at.desc()).limit(limit).offset(offset).all()

    # Денормализуем source_name из CrmIngestSource. Собираем всех
    # источников в один запрос: internal — по `source_key`, webhook —
    # по префиксу токена (source_ref_type имеет форму `webhook:<8char>`).
    # Небольшая таблица (десятки записей), берём целиком в память.
    source_by_key: dict[str, str] = {}
    token_pairs: list[tuple[str, str]] = []  # (token_prefix, name)
    try:
        from models.crm_ingest_source import CrmIngestSource
        for s in CrmIngestSource.query.all():
            if s.source_key:
                source_by_key[s.source_key] = s.name
            if s.token:
                token_pairs.append((s.token[:8], s.name))
    except Exception:
        pass

    def _resolve_source_name(ref_type: str | None) -> str | None:
        if not ref_type:
            return None
        if ref_type.startswith('webhook:'):
            prefix = ref_type.split(':', 1)[1]
            for tprefix, name in token_pairs:
                if tprefix == prefix:
                    return name
            return None
        return source_by_key.get(ref_type)

    # Батч-резолв DealSource + DealSourceVariant для карточек канбана —
    # показать «Источник» и «Доп. источник» без N+1.
    sources_by_id: dict[int, dict] = {}
    variants_by_id: dict[int, dict] = {}
    source_ids = {d.source_id for d in deals if d.source_id}
    variant_ids = {d.source_variant_id for d in deals if d.source_variant_id}
    if source_ids:
        try:
            from models.deal_source import DealSource
            for s in DealSource.query.filter(DealSource.id.in_(source_ids)).all():
                sources_by_id[s.id] = {'id': s.id, 'name': s.name, 'color': s.color}
        except Exception:
            pass
    if variant_ids:
        try:
            from models.deal_source import DealSourceVariant
            for v in DealSourceVariant.query.filter(DealSourceVariant.id.in_(variant_ids)).all():
                variants_by_id[v.id] = {
                    'id': v.id, 'parent_source_id': v.parent_source_id, 'name': v.name,
                }
        except Exception:
            pass

    out = []
    for d in deals:
        row = d.to_dict()
        row['source_name'] = _resolve_source_name(d.source_ref_type)
        row['deal_source'] = sources_by_id.get(d.source_id) if d.source_id else None
        row['source_variant'] = (
            variants_by_id.get(d.source_variant_id) if d.source_variant_id else None
        )
        out.append(row)

    return jsonify({
        'success': True,
        'deals': out,
        'total': total,
        'limit': limit,
        'offset': offset,
    }), 200


@deals_bp.route('/admin/deals/<int:did>', methods=['GET'])
@jwt_required()
def get_deal(did):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    return jsonify({'success': True, 'deal': _deal_full_dict(d)}), 200


@deals_bp.route('/admin/deals', methods=['POST'])
@jwt_required()
def create_deal():
    """
    Создаёт сделку. По умолчанию `responsible_user_id` = текущий юзер
    (если не указан явно) и создатель НЕ добавляется в deal_member —
    он уже responsible.

    Валидация: pipeline_id + stage_id обязательны и должны существовать;
    stage должна принадлежать этому pipeline.
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()

    data = request.get_json() or {}
    ok, msg, fields = _parse_deal_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    # Валидация: вариант источника должен принадлежать выбранному
    # родителю. source_id обязателен если выбран variant.
    err = _validate_source_variant_pair(
        fields.get('source_id'), fields.get('source_variant_id'),
    )
    if err:
        return err

    pipeline_id = fields['pipeline_id']
    stage_id = fields['stage_id']

    pipeline = DealPipeline.query.get(pipeline_id)
    if not pipeline:
        return jsonify({'error': 'Воронка не найдена'}), 404
    stage = DealStage.query.get(stage_id)
    if not stage or stage.pipeline_id != pipeline_id:
        return jsonify({'error': 'Стадия не найдена или не принадлежит воронке'}), 400

    responsible = fields.get('responsible_user_id', user_id)
    # По умолчанию открытая сделка, статус меняется автоматом когда move-stage
    # переносит в won/lost стадию.
    status = fields.get('status', 'open')

    # Мульти-контакты + primary. Если переданы contact_ids — primary
    # должен быть в этом же списке; иначе берём первый из contact_ids.
    # deal.client_id зеркалим с primary для обратной совместимости.
    contact_ids: list[int] = fields.get('contact_ids') or []
    primary_contact_id: int | None = fields.get('primary_contact_id')
    if contact_ids and (primary_contact_id is None or primary_contact_id not in contact_ids):
        primary_contact_id = contact_ids[0]
    # Если явного contact_ids нет, но передан client_id — создадим одну
    # привязку на client_id как primary (back-compat).
    legacy_client_id = fields.get('client_id')
    if not contact_ids and legacy_client_id:
        contact_ids = [legacy_client_id]
        primary_contact_id = legacy_client_id

    d = Deal(
        name=fields['name'],
        client_id=primary_contact_id or legacy_client_id,
        company_id=fields.get('company_id'),
        responsible_user_id=responsible,
        creator_id=user_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        amount=fields.get('amount'),
        currency=fields.get('currency', 'KZT'),
        expected_close_at=fields.get('expected_close_at'),
        priority=fields.get('priority', 'normal'),
        source=fields.get('source'),
        source_id=fields.get('source_id'),
        source_variant_id=fields.get('source_variant_id'),
        status=status,
        tags=fields.get('tags', []),
        notes=fields.get('notes'),
    )
    db.session.add(d)
    db.session.flush()

    # Записываем мультисвязь (если есть что писать).
    if contact_ids:
        from models.kp_company import DealContact
        for cid in contact_ids:
            db.session.add(DealContact(
                deal_id=d.id,
                client_id=cid,
                is_primary=(cid == primary_contact_id),
            ))

    db.session.add(DealActivity(
        deal_id=d.id, user_id=user_id, kind='created', payload={
            'pipeline_id': pipeline_id, 'stage_id': stage_id,
            'responsible_user_id': responsible,
        },
    ))
    db.session.commit()

    # Чат сделки создаётся ЛЕНИВО при первом открытии (см.
    # GET /api/admin/deals/<did>/chat-room, routes/deals.py:~1217).
    # Так пустые чаты по неоткрытым сделкам не плодятся — помойка не растёт.

    # Уведомление ответственному если это не сам создатель.
    if responsible and responsible != user_id:
        _safe_notify(
            user_id=responsible, kind='deal_assigned', section='deals',
            entity_type='deal', entity_id=d.id,
            payload={'deal_name': d.name, 'assigned_by': user_id},
            push_title='Новая сделка',
            push_body=f'Вам назначили: {d.name}',
            push_url=f'/admin/deals/{d.id}',
        )

    return jsonify({'success': True, 'deal': _deal_full_dict(d)}), 201


@deals_bp.route('/admin/deals/<int:did>', methods=['PUT'])
@jwt_required()
def update_deal(did):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав редактировать'}), 403

    data = request.get_json() or {}
    ok, msg, fields = _parse_deal_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    # Особый случай: смена stage_id через PUT считается move — идёт через
    # /move endpoint. Тут запрещаем менять stage_id (иначе можно обойти
    # авто-логику статуса и запись в activity).
    if 'stage_id' in fields and fields['stage_id'] != d.stage_id:
        return jsonify({'error': 'Смена стадии — через POST /deals/<id>/move'}), 400

    # Валидация source_variant_id. Берём effective значения с учётом того
    # что часть полей могла не прийти в partial-update.
    #   - если меняется source_id (без явного source_variant_id) — старый
    #     вариант сбрасываем автоматически, т.к. он был от другого parent;
    #   - если переданы оба — вариант должен принадлежать новому родителю.
    if 'source_id' in fields and fields.get('source_id') != d.source_id \
            and 'source_variant_id' not in fields:
        fields['source_variant_id'] = None
    eff_source_id = fields.get('source_id', d.source_id)
    eff_variant_id = fields.get('source_variant_id', d.source_variant_id)
    err = _validate_source_variant_pair(eff_source_id, eff_variant_id)
    if err:
        return err

    # Обработка мульти-контактов отдельно — это не колонка Deal.
    contact_ids_payload = fields.pop('contact_ids', None)
    primary_contact_id = fields.pop('primary_contact_id', None)
    if contact_ids_payload is not None:
        if contact_ids_payload and (
            primary_contact_id is None or primary_contact_id not in contact_ids_payload
        ):
            primary_contact_id = contact_ids_payload[0]
        from models.kp_company import DealContact
        DealContact.query.filter_by(deal_id=d.id).delete(synchronize_session=False)
        for cid in contact_ids_payload:
            db.session.add(DealContact(
                deal_id=d.id,
                client_id=cid,
                is_primary=(cid == primary_contact_id),
            ))
        # Синхронизируем deal.client_id с primary для back-compat.
        fields['client_id'] = primary_contact_id

    # Отслеживание изменений для activity.
    changes = {}
    for k, v in fields.items():
        if k in ('pipeline_id', 'stage_id'):
            continue  # см. выше
        old = getattr(d, k, None)
        if old != v:
            changes[k] = {'old': _json_safe(old), 'new': _json_safe(v)}
            setattr(d, k, v)

    d.updated_at = datetime.utcnow()

    if changes:
        # Спец-события ловим отдельно, остальное в field_changed.
        if 'responsible_user_id' in changes:
            db.session.add(DealActivity(
                deal_id=d.id, user_id=user_id, kind='responsible_changed',
                payload=changes['responsible_user_id'],
            ))
            # Синхронизируем ChatMember с новым ответственным.
            _sync_deal_chat_membership(
                d,
                old_responsible_id=changes['responsible_user_id']['old'],
                new_responsible_id=changes['responsible_user_id']['new'],
            )
        if len(changes) > 1 or 'responsible_user_id' not in changes:
            db.session.add(DealActivity(
                deal_id=d.id, user_id=user_id, kind='field_changed',
                payload={k: v for k, v in changes.items() if k != 'responsible_user_id'},
            ))

    db.session.commit()
    return jsonify({'success': True, 'deal': _deal_full_dict(d)}), 200


def _sync_deal_chat_membership(deal, old_responsible_id, new_responsible_id):
    """
    Синхронизирует ChatMember чата сделки с новым ответственным.
    - Добавляет нового ответственного (если его там ещё нет).
    - Убирает старого, если он не creator сделки и не писал ни одного
      сообщения в чате — чтобы чужие чаты не висели у бывшего ответственного.
    - Если чата нет (ленивое создание, его ещё не открывали) — noop.
    - Коммит делает caller.
    """
    if not deal:
        return
    try:
        from models.chat import ChatRoom, ChatMember, ChatMessage
        room = ChatRoom.query.filter_by(
            kind='deal', related_deal_id=deal.id,
        ).first()
        if not room:
            return
        if new_responsible_id:
            exists = ChatMember.query.filter_by(
                room_id=room.id, user_id=new_responsible_id,
            ).first()
            if not exists:
                db.session.add(ChatMember(
                    room_id=room.id, user_id=new_responsible_id,
                ))
        if old_responsible_id and old_responsible_id != new_responsible_id:
            # creator остаётся всегда, тех кто писал — тоже оставляем.
            if old_responsible_id != deal.creator_id:
                has_written = ChatMessage.query.filter_by(
                    room_id=room.id, author_id=old_responsible_id,
                ).first() is not None
                if not has_written:
                    ChatMember.query.filter_by(
                        room_id=room.id, user_id=old_responsible_id,
                    ).delete(synchronize_session=False)
    except Exception as e:
        print(
            f'⚠️ sync deal chat membership failed for deal {deal.id}: {e}',
            flush=True,
        )


def _json_safe(v):
    """Преобразует Decimal/datetime в JSON-serializable значение."""
    if isinstance(v, datetime):
        return v.isoformat()
    try:
        import decimal
        if isinstance(v, decimal.Decimal):
            return float(v)
    except ImportError:
        pass
    return v


@deals_bp.route('/admin/deals/<int:did>', methods=['DELETE'])
@jwt_required()
def delete_deal(did):
    """
    Удаление: admin любую, system — только свою (responsible=me).
    М2М-связи (members/kp/order/activity) удалятся каскадно (ondelete=CASCADE).
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = Deal.query.get(did)
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    # Удалять могут только owner и постановщик (creator). Ответственный
    # без прав creator/owner удалить не может — только править.
    from services.perms import is_owner as _is_owner
    if not (_is_owner(user_id) or d.creator_id == user_id):
        return jsonify({'error': 'Нет прав удалить'}), 403

    # Чат сделки: если пусто — уходит CASCADE вместе со сделкой. Если
    # в чате были сообщения — отвязываем (related_deal_id=NULL, чтоб
    # CASCADE не снёс) + помечаем архивным + сохраняем название для
    # /admin/chat сайдбара.
    try:
        from models.chat import ChatRoom, ChatMessage
        chat_room = ChatRoom.query.filter_by(kind='deal', related_deal_id=d.id).first()
        if chat_room:
            has_messages = db.session.query(
                ChatMessage.query.filter_by(room_id=chat_room.id).exists()
            ).scalar()
            if has_messages:
                chat_room.name = chat_room.name or f'Сделка №{d.id} — {d.name}'
                chat_room.related_deal_id = None
                chat_room.is_archived = True
                chat_room.archived_at = datetime.utcnow()
                db.session.flush()
    except Exception as e:
        print(f'⚠️ deal chat archive failed for deal {d.id}: {e}', flush=True)

    db.session.delete(d)
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Move stage (Kanban drag)
# ============================================================================

@deals_bp.route('/admin/deals/<int:did>/move', methods=['POST'])
@jwt_required()
def move_deal(did):
    """
    Перемещение сделки в другую стадию (drag на Kanban).

    Body: {"stage_id": N}

    Логика:
    - Стадия должна принадлежать текущей воронке сделки (иначе 400 —
      «между воронками надо явно менять pipeline_id через PUT»).
    - Если новая стадия типа 'won'/'lost' — deal.status автоматически
      меняется; при возврате в 'normal' — deal.status = 'open'.
    - Пишется deal_activity с kind='stage_changed' и payload'ом
      {from_stage_id, to_stage_id, from_status, to_status}.
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав редактировать'}), 403

    data = request.get_json() or {}
    try:
        new_stage_id = int(data['stage_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'stage_id обязателен'}), 400

    new_stage = DealStage.query.get(new_stage_id)
    if not new_stage:
        return jsonify({'error': 'Стадия не найдена'}), 404
    if new_stage.pipeline_id != d.pipeline_id:
        return jsonify({
            'error': 'Стадия из другой воронки. Смена воронки — через PUT /deals/<id>',
        }), 400

    if new_stage_id == d.stage_id:
        # Идемпотентный no-op.
        return jsonify({'success': True, 'deal': _deal_full_dict(d)}), 200

    from_stage_id = d.stage_id
    from_status = d.status

    d.stage_id = new_stage_id
    if new_stage.type == 'won':
        d.status = 'won'
    elif new_stage.type == 'lost':
        d.status = 'lost'
    else:
        d.status = 'open'
    d.updated_at = datetime.utcnow()

    db.session.add(DealActivity(
        deal_id=d.id, user_id=user_id, kind='stage_changed',
        payload={
            'from_stage_id': from_stage_id, 'to_stage_id': new_stage_id,
            'from_status': from_status, 'to_status': d.status,
        },
    ))
    db.session.commit()

    # Уведомляем ответственного (если это не он сам двигал), выбираем kind
    # по итоговому статусу — won/lost — иначе просто stage_changed.
    if d.responsible_user_id and d.responsible_user_id != user_id:
        if d.status == 'won':
            kind_n, title = 'deal_won', 'Сделка выиграна'
        elif d.status == 'lost':
            kind_n, title = 'deal_lost', 'Сделка проиграна'
        else:
            kind_n, title = 'deal_stage_changed', 'Стадия сделки изменена'
        _safe_notify(
            user_id=d.responsible_user_id, kind=kind_n, section='deals',
            entity_type='deal', entity_id=d.id,
            payload={'deal_name': d.name,
                     'from_stage_id': from_stage_id, 'to_stage_id': new_stage_id},
            push_title=title,
            push_body=d.name,
            push_url=f'/admin/deals/{d.id}',
        )

    return jsonify({'success': True, 'deal': _deal_full_dict(d)}), 200


# ============================================================================
# Members
# ============================================================================

@deals_bp.route('/admin/deals/<int:did>/members', methods=['POST'])
@jwt_required()
def add_member(did):
    """Body: {"user_id": N, "role": "participant" | "observer"}"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав приглашать'}), 403

    data = request.get_json() or {}
    try:
        target_uid = int(data['user_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'user_id обязателен'}), 400
    member_role = data.get('role') or 'participant'
    if member_role not in DEAL_MEMBER_ROLES:
        return jsonify({'error': f'role: {", ".join(DEAL_MEMBER_ROLES)}'}), 400

    if not SystemUser.query.get(target_uid):
        return jsonify({'error': 'Пользователь не найден'}), 404
    if target_uid == d.responsible_user_id:
        return jsonify({'error': 'Ответственный уже имеет полный доступ'}), 400

    exists = DealMember.query.filter_by(deal_id=did, user_id=target_uid).first()
    if exists:
        if exists.role != member_role:
            exists.role = member_role
            db.session.commit()
        return jsonify({'success': True, 'member': {
            'id': exists.id, 'user_id': exists.user_id, 'role': exists.role,
        }}), 200

    m = DealMember(deal_id=did, user_id=target_uid, role=member_role)
    db.session.add(m)
    db.session.add(DealActivity(
        deal_id=did, user_id=user_id, kind='member_added',
        payload={'user_id': target_uid, 'role': member_role},
    ))
    db.session.commit()

    # Синк chat-membership для чата сделки.
    try:
        from models.chat import ChatRoom, ChatMember
        chat_room = ChatRoom.query.filter_by(kind='deal', related_deal_id=did).first()
        if chat_room and not ChatMember.query.filter_by(
            room_id=chat_room.id, user_id=target_uid
        ).first():
            db.session.add(ChatMember(room_id=chat_room.id, user_id=target_uid))
            db.session.commit()
    except Exception as e:
        print(f'⚠️ deal chat member sync failed: {e}', flush=True)

    _safe_notify(
        user_id=target_uid, kind='deal_member_added', section='deals',
        entity_type='deal', entity_id=did,
        payload={'deal_name': d.name, 'role': member_role, 'added_by': user_id},
        push_title='Вас добавили в сделку',
        push_body=f'{d.name} ({"наблюдатель" if member_role == "observer" else "участник"})',
        push_url=f'/admin/deals/{did}',
    )

    return jsonify({'success': True, 'member': {
        'id': m.id, 'user_id': m.user_id, 'role': m.role,
    }}), 201


@deals_bp.route('/admin/deals/<int:did>/members/<int:uid>', methods=['DELETE'])
@jwt_required()
def remove_member(did, uid):
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    m = DealMember.query.filter_by(deal_id=did, user_id=uid).first()
    if not m:
        return jsonify({'error': 'Участник не найден'}), 404

    removed_role = m.role
    db.session.delete(m)
    db.session.add(DealActivity(
        deal_id=did, user_id=user_id, kind='member_removed',
        payload={'user_id': uid, 'role': removed_role},
    ))

    # Синхронизируем chat_member: убираем юзера из чата сделки, если он
    # больше нигде не связан со сделкой (не creator, не responsible,
    # не остался в других DealMember-ролях).
    try:
        from models.chat import ChatRoom, ChatMember
        chat_room = ChatRoom.query.filter_by(kind='deal', related_deal_id=did).first()
        if chat_room and d.creator_id != uid and d.responsible_user_id != uid:
            still_member = DealMember.query.filter(
                DealMember.deal_id == did,
                DealMember.user_id == uid,
                DealMember.id != m.id,
            ).first()
            if not still_member:
                ChatMember.query.filter_by(
                    room_id=chat_room.id, user_id=uid,
                ).delete()
    except Exception as e:
        print(f'⚠️ deal chat member remove sync failed: {e}', flush=True)

    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# KP attach/detach
# ============================================================================

@deals_bp.route('/admin/deals/<int:did>/kp', methods=['POST'])
@jwt_required()
def attach_kp(did):
    """Body: {"kp_history_id": N}"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    data = request.get_json() or {}
    try:
        kp_id = int(data['kp_history_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'kp_history_id обязателен'}), 400

    if not KPHistory.query.get(kp_id):
        return jsonify({'error': 'КП не найдено'}), 404
    if DealKp.query.filter_by(deal_id=did, kp_history_id=kp_id).first():
        return jsonify({'error': 'Это КП уже прикреплено'}), 409

    link = DealKp(deal_id=did, kp_history_id=kp_id, attached_by=user_id)
    db.session.add(link)
    db.session.add(DealActivity(
        deal_id=did, user_id=user_id, kind='kp_attached',
        payload={'kp_history_id': kp_id},
    ))
    db.session.commit()
    return jsonify({'success': True, 'kp': {
        'id': link.id, 'kp_history_id': link.kp_history_id,
    }}), 201


@deals_bp.route('/admin/deals/<int:did>/kp/<int:kid>', methods=['DELETE'])
@jwt_required()
def detach_kp(did, kid):
    """`kid` — это `deal_kp.id`, НЕ `kp_history.id`."""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    link = DealKp.query.filter_by(id=kid, deal_id=did).first()
    if not link:
        return jsonify({'error': 'Связь не найдена'}), 404

    kp_history_id = link.kp_history_id
    db.session.delete(link)
    db.session.add(DealActivity(
        deal_id=did, user_id=user_id, kind='kp_detached',
        payload={'kp_history_id': kp_history_id},
    ))
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Orders attach/detach
# ============================================================================

@deals_bp.route('/admin/deals/<int:did>/orders', methods=['POST'])
@jwt_required()
def attach_order(did):
    """Body: {"order_id": N}"""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    data = request.get_json() or {}
    try:
        oid = int(data['order_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'order_id обязателен'}), 400

    if not Order.query.get(oid):
        return jsonify({'error': 'Заказ не найден'}), 404
    if DealOrder.query.filter_by(deal_id=did, order_id=oid).first():
        return jsonify({'error': 'Заказ уже привязан'}), 409

    link = DealOrder(deal_id=did, order_id=oid)
    db.session.add(link)
    db.session.add(DealActivity(
        deal_id=did, user_id=user_id, kind='order_attached',
        payload={'order_id': oid},
    ))
    db.session.commit()
    return jsonify({'success': True, 'order': {
        'id': link.id, 'order_id': link.order_id,
    }}), 201


@deals_bp.route('/admin/deals/<int:did>/orders/<int:oid>', methods=['DELETE'])
@jwt_required()
def detach_order(did, oid):
    """`oid` — это `deal_order.id`."""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404
    if not _can_edit_deal(d, role, user_id):
        return jsonify({'error': 'Нет прав'}), 403

    link = DealOrder.query.filter_by(id=oid, deal_id=did).first()
    if not link:
        return jsonify({'error': 'Связь не найдена'}), 404

    order_id = link.order_id
    db.session.delete(link)
    db.session.add(DealActivity(
        deal_id=did, user_id=user_id, kind='order_detached',
        payload={'order_id': order_id},
    ))
    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Activity
# ============================================================================

@deals_bp.route('/admin/deals/<int:did>/activity', methods=['GET'])
@jwt_required()
def deal_activity(did):
    """Лента событий: последняя первой. Опц. пагинация limit/offset."""
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404

    limit = min(request.args.get('limit', 50, type=int), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)

    items = (
        DealActivity.query.filter_by(deal_id=did)
        .order_by(DealActivity.created_at.desc())
        .limit(limit).offset(offset).all()
    )
    return jsonify({
        'success': True,
        'activity': [a.to_dict() for a in items],
        'limit': limit,
        'offset': offset,
    }), 200


# ============================================================================
# Chat room helper
# ============================================================================

@deals_bp.route('/admin/deals/<int:did>/chat-room', methods=['GET'])
@jwt_required()
def get_deal_chat_room(did):
    """
    Возвращает id `chat_room` типа 'deal', привязанной к этой сделке
    (авто-создаётся в `create_deal` крючком). Фронт-карточка сделки
    вкладку «Чат» открывает по этому id — иначе пришлось бы искать
    комнату в списке всех.

    Не создаём room если её нет (сделка старше крючка) — просто 404,
    фронт покажет плейсхолдер.
    """
    err = _check_admin_or_system()
    if err:
        return err

    role, user_id = _current_role_and_id()
    d = _visible_deals_query(role, user_id).filter(Deal.id == did).first()
    if not d:
        return jsonify({'error': 'Сделка не найдена'}), 404

    from models.chat import ChatRoom, ChatMember
    room = ChatRoom.query.filter_by(kind='deal', related_deal_id=did).first()

    # Ленивая инициализация. Сделки созданные через ingest/webhook (до
    # того как эта фича появилась) чата не имели — создаём on-demand
    # при первом входе. Также ловит старые сделки, где auto-create
    # упал.
    dirty = False
    if not room:
        room = ChatRoom(kind='deal', related_deal_id=did)
        db.session.add(room)
        db.session.flush()
        dirty = True

    # Гарантируем membership только для тех кто явно связан со сделкой:
    # постановщик, ответственный, участники (соисполнители/наблюдатели).
    # Текущего юзера НЕ добавляем автоматически — иначе любой admin, кто
    # просто зашёл на карточку, получит доступ к чату навсегда.
    existing = {
        cm.user_id for cm in ChatMember.query.filter_by(room_id=room.id).all()
    }
    allowed_ids: set[int] = set()
    if d.creator_id:
        allowed_ids.add(d.creator_id)
    if d.responsible_user_id:
        allowed_ids.add(d.responsible_user_id)
    for m in DealMember.query.filter_by(deal_id=did).all():
        allowed_ids.add(m.user_id)
    # Owner получает membership автоматически — заглядывает в любой чат.
    from services.perms import is_owner as _is_owner
    if _is_owner(user_id):
        allowed_ids.add(user_id)
    for uid in allowed_ids - existing:
        db.session.add(ChatMember(room_id=room.id, user_id=uid))
        dirty = True

    if dirty:
        db.session.commit()

    # Все остальные — только если явный участник сделки.
    if user_id not in allowed_ids:
        return jsonify({'error': 'Нет доступа к чату сделки'}), 403

    return jsonify({'success': True, 'room_id': room.id}), 200
