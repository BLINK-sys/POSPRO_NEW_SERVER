"""
Публичный webhook-endpoint для ingest сделок из внешних систем.

Аутентификация — через токен в URL. Каждый `crm_ingest_source` с
`kind='webhook'` имеет свой уникальный `token` формата `wh_<32hex>`,
генерируемый на бэке при создании (см. routes/crm_sources.py).

Endpoints:
  POST /api/webhooks/crm/ingest/<token>   основной ingest
  GET  /api/webhooks/crm/ingest/<token>   health-check ({ok, name, ...})

Rate-limit — пока не ставим. Если начнёт бомбить — добавим Flask-Limiter
или Cloudflare-rule.
"""

from flask import Blueprint, request, jsonify

from services.crm_ingest import apply_webhook
from models.crm_ingest_source import CrmIngestSource


crm_webhooks_bp = Blueprint('crm_webhooks', __name__)


@crm_webhooks_bp.route('/webhooks/crm/ingest/<token>', methods=['GET'])
def health_check(token: str):
    """
    Health-check для админа-настройщика: даёт понять что URL живой и
    привязан к правильной воронке/стадии. Токен утечь может из URL —
    не отдаём ничего лишнего.
    """
    rule = CrmIngestSource.query.filter_by(kind='webhook', token=token).one_or_none()
    if not rule:
        return jsonify({'ok': False, 'error': 'Webhook не найден'}), 404
    return jsonify({
        'ok': True,
        'name': rule.name,
        'pipeline_id': rule.pipeline_id,
        'stage_id': rule.stage_id,
        'active': bool(rule.active),
    }), 200


@crm_webhooks_bp.route('/webhooks/crm/ingest/<token>', methods=['POST'])
def ingest_webhook(token: str):
    """
    Приём сделки от внешнего сервиса. Тело — свободный JSON, формат см.
    в 31 CRM (Обсидиан-заметка).

    Ответ:
      201 — сделка создана (`deal_id`, `responsible_id`, `dedupe=false`)
      200 — сделка уже была, вернули существующий id (dedupe=true)
      403 — webhook не активен
      404 — токен не найден
      400 — невалидный JSON
    """
    if not request.is_json:
        return jsonify({'ok': False, 'error': 'Ожидался JSON body'}), 400

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'ok': False, 'error': 'Payload должен быть объектом'}), 400

    result = apply_webhook(token, payload)
    if not result.ok:
        # apply_webhook возвращает only "не найден или выключен" — маркируем 404
        # (не 403), чтобы источник не узнал разницу между «токен неверный» и
        # «токен верный, но выключен». Best-practice для webhooks.
        return jsonify({'ok': False, 'error': result.error}), 404

    return jsonify({
        'ok': True,
        'deal_id': result.deal_id,
        'responsible_id': result.responsible_id,
        'dedupe': result.dedupe,
    }), (200 if result.dedupe else 201)
