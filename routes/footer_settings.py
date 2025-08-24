from flask import Blueprint, request, jsonify
from extensions import db
from models.footer_settings import FooterSetting

footer_settings_bp = Blueprint('footer_settings', __name__)


@footer_settings_bp.route('/footer-settings', methods=['GET'])
def get_footer_settings():
    settings = FooterSetting.query.first()
    if not settings:
        # Возвращаем дефолтные значения, если нет данных в БД
        return jsonify({
            'description': 'PosPro - ваш надежный партнер в мире качественных товаров. Мы предлагаем широкий ассортимент и лучший сервис.',
            'instagram_url': 'https://instagram.com/pospro',
            'whatsapp_url': 'https://wa.me/77771234567',
            'telegram_url': 'https://t.me/pospro',
            'phone': '+7 (727) 123-45-67',
            'email': 'support@pospro.kz',
            'address': 'г. Алматы, ул. Достык, 105',
            'working_hours': 'Пн-Пт 9:00 - 18:00'
        })

    return jsonify({
        'description': settings.description,
        'instagram_url': settings.instagram_url,
        'whatsapp_url': settings.whatsapp_url,
        'telegram_url': settings.telegram_url,
        'phone': settings.phone,
        'email': settings.email,
        'address': settings.address,
        'working_hours': settings.working_hours
    })


@footer_settings_bp.route('/footer-settings', methods=['POST', 'PUT'])
def save_footer_settings():
    data = request.get_json()

    settings = FooterSetting.query.first()
    if not settings:
        settings = FooterSetting()
        db.session.add(settings)

    settings.description = data.get('description')
    settings.instagram_url = data.get('instagram_url')
    settings.whatsapp_url = data.get('whatsapp_url')
    settings.telegram_url = data.get('telegram_url')
    settings.phone = data.get('phone')
    settings.email = data.get('email')
    settings.address = data.get('address')
    settings.working_hours = data.get('working_hours')

    db.session.commit()
    return jsonify({'message': 'Настройки подвала сохранены'})
