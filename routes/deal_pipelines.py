"""
CRUD воронок сделок и их стадий.

Access: только `role='admin'` — воронки/стадии это org-wide настройка,
менеджеры (`role='system'`) работают со сделками ВНУТРИ воронок но
структуру не трогают. См. развилку «настраиваются админом» в
Обсидиан-плане (31 CRM…).

Endpoints:
  GET    /api/admin/deal-pipelines            список всех
  POST   /api/admin/deal-pipelines            создать
  GET    /api/admin/deal-pipelines/<id>       детали + стадии
  PUT    /api/admin/deal-pipelines/<id>       обновить (name/active)
  DELETE /api/admin/deal-pipelines/<id>       удалить (блок если есть сделки)
  POST   /api/admin/deal-pipelines/reorder    сортировка (drag&drop)

  GET    /api/admin/deal-stages?pipeline_id=  список стадий воронки
  POST   /api/admin/deal-stages               создать
  PUT    /api/admin/deal-stages/<id>          обновить (name/color/type)
  DELETE /api/admin/deal-stages/<id>          удалить (блок если есть сделки)
  POST   /api/admin/deal-stages/reorder       сортировка

Защита от удаления: если хоть одна сделка ссылается на воронку/стадию,
возвращаем 409 с количеством привязанных сделок — UI покажет понятный
текст «сначала переместите сделки в другую стадию/воронку».
"""

from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models.deal_pipeline import DealPipeline, DealStage, DEAL_STAGE_TYPES
from models.deal import Deal


deal_pipelines_bp = Blueprint('deal_pipelines', __name__)


# ============================================================================
# Auth helper
# ============================================================================

def _check_admin_only():
    """
    Воронки/стадии настраивает только `role='admin'`. Менеджеры (system)
    редактируют СДЕЛКИ но не структуру воронки.
    """
    role = (get_jwt() or {}).get('role')
    if role != 'admin':
        return jsonify({'error': 'Настройка воронок доступна только администратору'}), 403
    return None


# ============================================================================
# Валидация
# ============================================================================

def _parse_pipeline_payload(data: dict, *, partial: bool = False):
    """Возвращает `(ok, error, fields)` для POST/PUT /deal-pipelines."""
    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название воронки обязательно', {}

    fields = {}
    if name is not None:
        fields['name'] = name
    if 'active' in data:
        fields['active'] = bool(data.get('active'))
    return True, None, fields


def _parse_stage_payload(data: dict, *, partial: bool = False):
    """Возвращает `(ok, error, fields)` для POST/PUT /deal-stages."""
    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название стадии обязательно', {}

    color = (data.get('color') or '').strip() or None
    if color and not (color.startswith('#') and len(color) in (4, 7, 9)):
        return False, 'Цвет должен быть в hex-формате (#RRGGBB или #RGB)', {}

    stype = data.get('type')
    if stype is not None and stype not in DEAL_STAGE_TYPES:
        return False, f'Некорректный тип стадии. Допустимо: {", ".join(DEAL_STAGE_TYPES)}', {}

    fields = {}
    if name is not None:
        fields['name'] = name
    if color is not None:
        fields['color'] = color
    if stype is not None:
        fields['type'] = stype
    if not partial and 'pipeline_id' in data:
        try:
            fields['pipeline_id'] = int(data['pipeline_id'])
        except (TypeError, ValueError):
            return False, 'pipeline_id должен быть числом', {}
    return True, None, fields


# ============================================================================
# Pipelines
# ============================================================================

@deal_pipelines_bp.route('/admin/deal-pipelines', methods=['GET'])
@jwt_required()
def list_pipelines():
    """
    Возвращает все воронки, отсортированные по `order`. Если передан
    `?with_stages=1` — включает стадии в ответ (для UI Kanban при
    первичной загрузке — одним запросом всё сразу).

    Менеджеры (system) могут читать список, чтобы Kanban мог отрисоваться —
    write защищён на уровне отдельных endpoint'ов.
    """
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403

    include_stages = request.args.get('with_stages') == '1'
    pipelines = DealPipeline.query.order_by(DealPipeline.order, DealPipeline.id).all()
    return jsonify({
        'success': True,
        'pipelines': [p.to_dict(include_stages=include_stages) for p in pipelines],
    }), 200


@deal_pipelines_bp.route('/admin/deal-pipelines/<int:pid>', methods=['GET'])
@jwt_required()
def get_pipeline(pid):
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403

    p = DealPipeline.query.get(pid)
    if not p:
        return jsonify({'error': 'Воронка не найдена'}), 404
    return jsonify({'success': True, 'pipeline': p.to_dict(include_stages=True)}), 200


@deal_pipelines_bp.route('/admin/deal-pipelines', methods=['POST'])
@jwt_required()
def create_pipeline():
    err = _check_admin_only()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _parse_pipeline_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    # Ставим в конец списка по order.
    max_order = db.session.query(db.func.coalesce(db.func.max(DealPipeline.order), -1)).scalar()
    p = DealPipeline(
        name=fields['name'],
        order=int(max_order) + 1,
        active=fields.get('active', True),
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({'success': True, 'pipeline': p.to_dict(include_stages=True)}), 201


@deal_pipelines_bp.route('/admin/deal-pipelines/<int:pid>', methods=['PUT'])
@jwt_required()
def update_pipeline(pid):
    err = _check_admin_only()
    if err:
        return err

    p = DealPipeline.query.get(pid)
    if not p:
        return jsonify({'error': 'Воронка не найдена'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_pipeline_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in fields:
        p.name = fields['name']
    if 'active' in fields:
        p.active = fields['active']
    p.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'pipeline': p.to_dict(include_stages=True)}), 200


@deal_pipelines_bp.route('/admin/deal-pipelines/<int:pid>', methods=['DELETE'])
@jwt_required()
def delete_pipeline(pid):
    """
    Удаляет воронку. Блокируется, если к ней привязаны сделки — UI должен
    сначала предложить админу переместить сделки в другую воронку.
    Стадии удалятся каскадно (ondelete=CASCADE в модели).
    """
    err = _check_admin_only()
    if err:
        return err

    p = DealPipeline.query.get(pid)
    if not p:
        return jsonify({'error': 'Воронка не найдена'}), 404

    in_use = Deal.query.filter_by(pipeline_id=pid).count()
    if in_use > 0:
        return jsonify({
            'error': f'Нельзя удалить — в воронке {in_use} сделок. '
                     f'Сначала переместите их в другую воронку.',
            'in_use_count': in_use,
        }), 409

    db.session.delete(p)
    db.session.commit()
    return jsonify({'success': True}), 200


@deal_pipelines_bp.route('/admin/deal-pipelines/reorder', methods=['POST'])
@jwt_required()
def reorder_pipelines():
    """
    Принимает `[{id, order}, ...]` — тот же формат что и в `reorder`
    для section-cards/homepage-blocks. Обновляет `order` пачкой.
    """
    err = _check_admin_only()
    if err:
        return err

    payload = request.get_json()
    if not isinstance(payload, list):
        return jsonify({'error': 'Ожидался массив {id, order}'}), 400

    # Достаём все pipeline'ы одним запросом, потом пробегаем по payload.
    ids = [item.get('id') for item in payload if isinstance(item, dict)]
    pipelines = {p.id: p for p in DealPipeline.query.filter(DealPipeline.id.in_(ids)).all()}

    for item in payload:
        if not isinstance(item, dict):
            continue
        pid = item.get('id')
        order = item.get('order')
        if pid in pipelines and isinstance(order, int):
            pipelines[pid].order = order

    db.session.commit()
    return jsonify({'success': True}), 200


# ============================================================================
# Stages
# ============================================================================

@deal_pipelines_bp.route('/admin/deal-stages', methods=['GET'])
@jwt_required()
def list_stages():
    """
    Список стадий. С `?pipeline_id=N` — только стадии этой воронки.
    Без фильтра — все стадии всех воронок (для админ-UI где надо выбрать
    целевую стадию для перемещения сделки между воронками).
    """
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403

    q = DealStage.query
    pipeline_id = request.args.get('pipeline_id')
    if pipeline_id:
        try:
            q = q.filter_by(pipeline_id=int(pipeline_id))
        except ValueError:
            return jsonify({'error': 'pipeline_id должен быть числом'}), 400

    stages = q.order_by(DealStage.pipeline_id, DealStage.order, DealStage.id).all()
    return jsonify({
        'success': True,
        'stages': [s.to_dict() for s in stages],
    }), 200


@deal_pipelines_bp.route('/admin/deal-stages', methods=['POST'])
@jwt_required()
def create_stage():
    err = _check_admin_only()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _parse_stage_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    pipeline_id = fields.get('pipeline_id')
    if pipeline_id is None:
        return jsonify({'error': 'pipeline_id обязателен'}), 400
    if not DealPipeline.query.get(pipeline_id):
        return jsonify({'error': 'Воронка не найдена'}), 404

    # В конец списка стадий воронки.
    max_order = db.session.query(
        db.func.coalesce(db.func.max(DealStage.order), -1)
    ).filter_by(pipeline_id=pipeline_id).scalar()

    s = DealStage(
        pipeline_id=pipeline_id,
        name=fields['name'],
        color=fields.get('color', '#94a3b8'),
        order=int(max_order) + 1,
        type=fields.get('type', 'normal'),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify({'success': True, 'stage': s.to_dict()}), 201


@deal_pipelines_bp.route('/admin/deal-stages/<int:sid>', methods=['PUT'])
@jwt_required()
def update_stage(sid):
    err = _check_admin_only()
    if err:
        return err

    s = DealStage.query.get(sid)
    if not s:
        return jsonify({'error': 'Стадия не найдена'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_stage_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in fields:
        s.name = fields['name']
    if 'color' in fields:
        s.color = fields['color']
    if 'type' in fields:
        s.type = fields['type']
    s.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'stage': s.to_dict()}), 200


@deal_pipelines_bp.route('/admin/deal-stages/<int:sid>', methods=['DELETE'])
@jwt_required()
def delete_stage(sid):
    """
    Блокируется если к стадии привязаны сделки — UI должен предложить
    переместить их в другую стадию.
    """
    err = _check_admin_only()
    if err:
        return err

    s = DealStage.query.get(sid)
    if not s:
        return jsonify({'error': 'Стадия не найдена'}), 404

    in_use = Deal.query.filter_by(stage_id=sid).count()
    if in_use > 0:
        return jsonify({
            'error': f'Нельзя удалить — в стадии {in_use} сделок. '
                     f'Сначала переместите их в другую стадию.',
            'in_use_count': in_use,
        }), 409

    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True}), 200


@deal_pipelines_bp.route('/admin/deal-stages/reorder', methods=['POST'])
@jwt_required()
def reorder_stages():
    """
    Принимает `[{id, order}, ...]`. Проверяет, что все стадии из одной
    воронки (нельзя reorder'ить между воронками одним запросом — это
    ошибка UI).
    """
    err = _check_admin_only()
    if err:
        return err

    payload = request.get_json()
    if not isinstance(payload, list):
        return jsonify({'error': 'Ожидался массив {id, order}'}), 400

    ids = [item.get('id') for item in payload if isinstance(item, dict)]
    stages = {s.id: s for s in DealStage.query.filter(DealStage.id.in_(ids)).all()}

    pipeline_ids = {s.pipeline_id for s in stages.values()}
    if len(pipeline_ids) > 1:
        return jsonify({'error': 'Все стадии в запросе должны быть из одной воронки'}), 400

    for item in payload:
        if not isinstance(item, dict):
            continue
        sid = item.get('id')
        order = item.get('order')
        if sid in stages and isinstance(order, int):
            stages[sid].order = order

    db.session.commit()
    return jsonify({'success': True}), 200
