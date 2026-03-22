"""
API routes for import integrations.
SSE endpoint for real-time progress streaming.
"""

import json
import threading
import time

from flask import Blueprint, Response, jsonify, stream_with_context
from flask_jwt_extended import get_jwt, jwt_required

from integrations.bio.pipeline import run_full_pipeline
from integrations.bio.progress import progress

integrations_bp = Blueprint('integrations', __name__)


def _check_admin():
    """Returns error response if user is not admin/system, else None."""
    jwt_data = get_jwt()
    role = jwt_data.get('role', 'client')
    if role not in ('admin', 'system'):
        return jsonify({'error': 'Доступ запрещён'}), 403
    return None


@integrations_bp.route('/integrations/sources', methods=['GET'])
@jwt_required()
def list_sources():
    err = _check_admin()
    if err:
        return err

    return jsonify({
        'sources': [
            {
                'id': 'bio',
                'name': 'BIO (bioshop.ru)',
                'description': 'Импорт товаров из каталога BIO',
                'estimated_duration': '~2:40 ч.',
                'status': progress.status,
                'last_run': progress.finished_at
            }
        ]
    })


@integrations_bp.route('/integrations/bio/start', methods=['POST'])
@jwt_required()
def start_bio_import():
    err = _check_admin()
    if err:
        return err

    if progress.status == 'running':
        return jsonify({'error': 'Импорт уже запущен'}), 409

    thread = threading.Thread(target=run_full_pipeline, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': 'Импорт запущен'}), 200


@integrations_bp.route('/integrations/bio/status', methods=['GET'])
@jwt_required()
def bio_import_status_sse():
    err = _check_admin()
    if err:
        return err

    def generate():
        while True:
            data = json.dumps(progress.to_dict(), ensure_ascii=False)
            yield f"data: {data}\n\n"
            if progress.status in ('completed', 'error', 'idle'):
                # Send final state one more time then stop
                break
            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@integrations_bp.route('/integrations/bio/status-poll', methods=['GET'])
@jwt_required()
def bio_import_status_poll():
    """Polling fallback if SSE doesn't work through proxy."""
    err = _check_admin()
    if err:
        return err

    return jsonify(progress.to_dict())
