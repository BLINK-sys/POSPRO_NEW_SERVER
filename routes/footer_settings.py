"""
GET/PUT настроек подвала. В одной записи:
  - текст «о компании» (однострочник), соцсети, контактная информация;
  - юридические реквизиты (выводятся в подвале кратким блоком и на
    отдельной странице `/requisites`);
  - contacts_order / info_order — JSON-массивы ключей в нужном порядке
    для колонок «Контакты» / «Информация». NULL = дефолтный порядок,
    зашитый во фронте.

Публичный путь не требует авторизации, но save-операция должна быть
доступна только админам — JWT-гвард оставлен на уровне зеркала через
Next-прокси (во фронте стоит проверка роли перед вызовом).
"""

import json

from flask import Blueprint, request, jsonify

from extensions import db
from models.footer_settings import FooterSetting


footer_settings_bp = Blueprint('footer_settings', __name__)


_EDITABLE_FIELDS = (
    'description',
    'instagram_url', 'whatsapp_url', 'telegram_url',
    'phone', 'email', 'address', 'working_hours',
    'legal_name', 'bin_number', 'legal_address',
    'bank_name', 'bank_bic', 'bank_iik', 'bank_kbe',
)


def _parse_order(raw):
    """JSON-массив строк. Невалидный → None (фронт возьмёт дефолтный порядок)."""
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return [str(x) for x in data if isinstance(x, (str, int))]


def _serialize(settings: FooterSetting | None) -> dict:
    if settings is None:
        # Дефолтные значения — pre-set на старте, до первой записи.
        return {
            'description': 'PosPro — профессиональное оборудование для бизнеса.',
            'instagram_url': '', 'whatsapp_url': '', 'telegram_url': '',
            'phone': '', 'email': '', 'address': '', 'working_hours': '',
            'legal_name': '', 'bin_number': '', 'legal_address': '',
            'bank_name': '', 'bank_bic': '', 'bank_iik': '', 'bank_kbe': '',
            'contacts_order': None, 'info_order': None,
        }
    out = {f: getattr(settings, f, None) or '' for f in _EDITABLE_FIELDS}
    out['contacts_order'] = _parse_order(settings.contacts_order)
    out['info_order'] = _parse_order(settings.info_order)
    return out


@footer_settings_bp.route('/footer-settings', methods=['GET'])
def get_footer_settings():
    settings = FooterSetting.query.first()
    return jsonify(_serialize(settings))


@footer_settings_bp.route('/footer-settings', methods=['POST', 'PUT'])
def save_footer_settings():
    data = request.get_json() or {}

    settings = FooterSetting.query.first()
    if not settings:
        settings = FooterSetting()
        db.session.add(settings)

    for f in _EDITABLE_FIELDS:
        if f in data:
            setattr(settings, f, data.get(f))

    if 'contacts_order' in data:
        order = _parse_order(data.get('contacts_order'))
        settings.contacts_order = json.dumps(order, ensure_ascii=False) if order else None
    if 'info_order' in data:
        order = _parse_order(data.get('info_order'))
        settings.info_order = json.dumps(order, ensure_ascii=False) if order else None

    db.session.commit()
    return jsonify(_serialize(settings))
