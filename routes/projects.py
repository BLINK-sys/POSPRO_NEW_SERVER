"""
CRUD-ручки справочника проектов для CRM-задач.

Проект — верхнеуровневый контейнер для задач, не привязанных к
конкретной сделке. См. models/project.py.

Endpoints (все под `/api/admin`):
  GET    /projects              список
  POST   /projects              создать
  PUT    /projects/<id>         обновить (name/color/description)
  DELETE /projects/<id>         удалить (task.project_id → NULL, задачи остаются)

Auth: admin/system (те же правила что и у сделок/задач).
"""

from __future__ import annotations

import re

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models.project import Project
from models.task import Task


projects_bp = Blueprint('projects', __name__)


HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _check_admin_or_system():
    role = (get_jwt() or {}).get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


def _current_user_id() -> int | None:
    try:
        return int(get_jwt_identity()) if get_jwt_identity() else None
    except (TypeError, ValueError):
        return None


def _parse_payload(data: dict, *, partial: bool = False):
    """Валидация тела POST/PUT /projects."""
    fields: dict = {}

    name = (data.get('name') or '').strip() or None
    if not partial and not name:
        return False, 'Название проекта обязательно', {}
    if name is not None:
        if len(name) > 255:
            return False, 'Название слишком длинное (макс 255)', {}
        fields['name'] = name

    if 'color' in data:
        color = (data.get('color') or '').strip() or '#facc15'
        if not HEX_RE.match(color):
            return False, 'color должен быть в формате #RRGGBB', {}
        fields['color'] = color

    if 'description' in data:
        desc = data.get('description')
        fields['description'] = (desc or '').strip() or None

    return True, None, fields


@projects_bp.route('/admin/projects', methods=['GET'])
@jwt_required()
def list_projects():
    err = _check_admin_or_system()
    if err:
        return err

    q = (request.args.get('q') or '').strip().lower()
    query = Project.query
    if q:
        query = query.filter(db.func.lower(Project.name).like(f'%{q}%'))
    projects = query.order_by(Project.name.asc()).all()

    # Денормализуем счётчик задач одним запросом — фронт использует
    # его в списке справочника и в пикере.
    counts = dict(
        db.session.query(Task.project_id, db.func.count(Task.id))
        .filter(Task.project_id.isnot(None))
        .group_by(Task.project_id)
        .all()
    )
    out = []
    for p in projects:
        row = p.to_dict()
        row['task_count'] = int(counts.get(p.id, 0))
        out.append(row)

    return jsonify({'success': True, 'projects': out}), 200


@projects_bp.route('/admin/projects', methods=['POST'])
@jwt_required()
def create_project():
    err = _check_admin_or_system()
    if err:
        return err

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data)
    if not ok:
        return jsonify({'error': msg}), 400

    # Уникальность имени: постреснем сразу 409, не полагаясь на IntegrityError.
    dup = Project.query.filter(
        db.func.lower(Project.name) == fields['name'].lower(),
    ).first()
    if dup:
        return jsonify({'error': 'Проект с таким названием уже существует'}), 409

    p = Project(
        name=fields['name'],
        color=fields.get('color', '#facc15'),
        description=fields.get('description'),
        created_by=_current_user_id(),
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({'success': True, 'project': p.to_dict()}), 201


@projects_bp.route('/admin/projects/<int:pid>', methods=['PUT'])
@jwt_required()
def update_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404

    data = request.get_json() or {}
    ok, msg, fields = _parse_payload(data, partial=True)
    if not ok:
        return jsonify({'error': msg}), 400

    if 'name' in fields and fields['name'].lower() != (p.name or '').lower():
        dup = Project.query.filter(
            db.func.lower(Project.name) == fields['name'].lower(),
            Project.id != pid,
        ).first()
        if dup:
            return jsonify({'error': 'Проект с таким названием уже существует'}), 409

    for k, v in fields.items():
        setattr(p, k, v)
    db.session.commit()
    return jsonify({'success': True, 'project': p.to_dict()}), 200


@projects_bp.route('/admin/projects/<int:pid>', methods=['DELETE'])
@jwt_required()
def delete_project(pid):
    err = _check_admin_or_system()
    if err:
        return err
    p = Project.query.get(pid)
    if not p:
        return jsonify({'error': 'Проект не найден'}), 404

    # SET NULL на task.project_id — задачи не удаляются, просто теряют
    # привязку. Обработку делает FK ON DELETE, руками не трогаем.
    db.session.delete(p)
    db.session.commit()
    return jsonify({'success': True}), 200
