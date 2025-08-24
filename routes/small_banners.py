from flask import Blueprint, request, jsonify
from extensions import db
from models.small_banner_card import SmallBanner

small_banner_bp = Blueprint('small_banner_bp', __name__)


@small_banner_bp.route('/small-banners', methods=['GET'])
def get_all_small_banners():
    banners = SmallBanner.query.order_by(SmallBanner.id.desc()).all()
    return jsonify([
        {
            'id': b.id,
            'title': b.title,
            'description': b.description,
            'image_url': b.image_url,
            'button_text': b.button_text,
            'button_text_color': b.button_text_color,
            'button_bg_color': b.button_bg_color,
            'button_link': b.button_link,
            'card_bg_color': b.card_bg_color,
            'show_button': b.show_button
        } for b in banners
    ])


@small_banner_bp.route('/small-banners', methods=['POST'])
def create_small_banner():
    data = request.json
    banner = SmallBanner(**data)
    db.session.add(banner)
    db.session.commit()
    return jsonify({'message': 'Карточка создана', 'id': banner.id})


@small_banner_bp.route('/small-banners/<int:id>', methods=['PATCH'])
def update_small_banner(id):
    banner = SmallBanner.query.get_or_404(id)
    for key, value in request.json.items():
        setattr(banner, key, value)
    db.session.commit()
    return jsonify({'message': 'Карточка обновлена'})


@small_banner_bp.route('/small-banners/<int:id>', methods=['DELETE'])
def delete_small_banner(id):
    banner = SmallBanner.query.get_or_404(id)
    db.session.delete(banner)
    db.session.commit()
    return jsonify({'message': 'Удалено'})


