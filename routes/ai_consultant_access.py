"""
AI Consultant access management.

Endpoints:
- GET /api/ai-consultant/access — public, optional JWT. Returns
  {has_access: bool} for the current viewer (guest or authenticated).
  Used by the header to decide whether to show the "AI консультант"
  button, and by /ai page to gate route access.

- GET /api/admin/ai-consultant/settings — owner-only. Returns the full
  settings row plus a roster of system users so the admin UI can render
  per-user toggles.

- PUT /api/admin/ai-consultant/settings — owner-only. Replaces the
  settings.

Owner is hard-coded as bocan.anton@mail.ru (admin role). The hardcode
is intentional — this is a global feature gate, not a per-permission
ACL, so spreading it via `system_users.access_*` would be misleading.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity

from extensions import db
from models.ai_consultant_access import AIConsultantAccess
from models.systemuser import SystemUser
from models.user import User

ai_consultant_access_bp = Blueprint('ai_consultant_access', __name__)

OWNER_EMAIL = 'bocan.anton@mail.ru'


def _resolve_viewer():
    """
    Inspect the optional JWT and return a dict describing the caller:
      {kind: 'guest' | 'client' | 'wholesale' | 'system' | 'admin',
       user_id: int | None, email: str | None}
    """
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return {'kind': 'guest', 'user_id': None, 'email': None}

    identity = get_jwt_identity()
    if not identity:
        return {'kind': 'guest', 'user_id': None, 'email': None}

    claims = get_jwt() or {}
    role = claims.get('role') or 'client'

    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        return {'kind': 'guest', 'user_id': None, 'email': None}

    if role in ('admin', 'system'):
        su = SystemUser.query.get(user_id)
        if not su:
            return {'kind': 'guest', 'user_id': None, 'email': None}
        return {
            'kind': 'admin' if (su.email or '').lower() == OWNER_EMAIL else 'system',
            'user_id': user_id,
            'email': su.email,
        }

    user = User.query.get(user_id)
    if not user:
        return {'kind': 'guest', 'user_id': None, 'email': None}
    return {
        'kind': 'wholesale' if user.is_wholesale else 'client',
        'user_id': user_id,
        'email': user.email,
    }


def _has_access(viewer, settings: AIConsultantAccess) -> bool:
    """Apply the settings to the viewer's kind and produce a bool."""
    if viewer['kind'] == 'admin':  # owner always has access
        return True
    if viewer['kind'] == 'guest':
        return bool(settings.allow_guest)
    if viewer['kind'] == 'client':
        return bool(settings.allow_registered)
    if viewer['kind'] == 'wholesale':
        return bool(settings.allow_wholesale)
    if viewer['kind'] == 'system':
        return viewer['user_id'] in (settings.allowed_system_user_ids or [])
    return False


def _has_product_import_access(viewer, settings: AIConsultantAccess) -> bool:
    """
    Product Import is only relevant for system users (creating products is an
    admin action). Owner always has access; everyone else must be opted in
    via allowed_product_import_user_ids.
    """
    if viewer['kind'] == 'admin':
        return True
    if viewer['kind'] == 'system':
        return viewer['user_id'] in (settings.allowed_product_import_user_ids or [])
    return False


# ───────────────────────────────────────────────────────────────────
# Public access check — used by header + /ai page on the frontend
# ───────────────────────────────────────────────────────────────────

@ai_consultant_access_bp.route('/ai-consultant/access', methods=['GET'])
def check_access():
    viewer = _resolve_viewer()
    settings = AIConsultantAccess.get_or_create()
    return jsonify({
        'has_access': _has_access(viewer, settings),
        'kind': viewer['kind'],
    }), 200


@ai_consultant_access_bp.route('/product-import/access', methods=['GET'])
def check_product_import_access():
    """
    Used by the admin product create form to decide whether to render the
    "Импорт из URL" button. Backend enforces the same check on the actual
    auto-fill endpoint, so this is purely a UI hint.
    """
    viewer = _resolve_viewer()
    settings = AIConsultantAccess.get_or_create()
    return jsonify({
        'has_access': _has_product_import_access(viewer, settings),
        'kind': viewer['kind'],
    }), 200


# ───────────────────────────────────────────────────────────────────
# Admin (owner-only) endpoints
# ───────────────────────────────────────────────────────────────────

def _require_owner():
    """Validate that the caller is the hardcoded owner. Returns None on
    success, or a (response, status) tuple to short-circuit on failure."""
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({'error': 'Требуется авторизация'}), 401
    claims = get_jwt() or {}
    role = claims.get('role')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({'error': 'Доступ запрещён'}), 403
    su = SystemUser.query.get(user_id)
    if not su or (su.email or '').lower() != OWNER_EMAIL:
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


@ai_consultant_access_bp.route('/admin/ai-consultant/settings', methods=['GET'])
def get_settings():
    err = _require_owner()
    if err is not None:
        return err

    settings = AIConsultantAccess.get_or_create()
    system_users = SystemUser.query.order_by(SystemUser.full_name).all()
    return jsonify({
        'settings': settings.to_dict(),
        'system_users': [
            {'id': u.id, 'email': u.email, 'full_name': u.full_name}
            for u in system_users
        ],
    }), 200


@ai_consultant_access_bp.route('/admin/ai-consultant/settings', methods=['PUT'])
def update_settings():
    err = _require_owner()
    if err is not None:
        return err

    data = request.get_json(silent=True) or {}
    settings = AIConsultantAccess.get_or_create()

    if 'allow_guest' in data:
        settings.allow_guest = bool(data['allow_guest'])
    if 'allow_registered' in data:
        settings.allow_registered = bool(data['allow_registered'])
    if 'allow_wholesale' in data:
        settings.allow_wholesale = bool(data['allow_wholesale'])
    def _clean_user_ids(ids_raw):
        """Validate id list — keep only ints that exist in system_users, dedupe, sort."""
        if not isinstance(ids_raw, list):
            return None  # caller signals error
        cleaned: list[int] = []
        seen = set()
        for v in ids_raw:
            try:
                vid = int(v)
            except (TypeError, ValueError):
                continue
            if vid in seen:
                continue
            if SystemUser.query.get(vid):
                cleaned.append(vid)
                seen.add(vid)
        return cleaned

    if 'allowed_system_user_ids' in data:
        cleaned = _clean_user_ids(data['allowed_system_user_ids'])
        if cleaned is None:
            return jsonify({'error': 'allowed_system_user_ids должен быть массивом'}), 400
        settings.allowed_system_user_ids = cleaned

    if 'allowed_product_import_user_ids' in data:
        cleaned = _clean_user_ids(data['allowed_product_import_user_ids'])
        if cleaned is None:
            return jsonify({'error': 'allowed_product_import_user_ids должен быть массивом'}), 400
        settings.allowed_product_import_user_ids = cleaned

    # Track who made the change (for audit display in the UI).
    try:
        editor_id = int(get_jwt_identity())
        editor = SystemUser.query.get(editor_id)
        if editor:
            settings.updated_by_email = editor.email
    except Exception:
        pass

    db.session.commit()

    return jsonify({
        'success': True,
        'settings': settings.to_dict(),
    }), 200
