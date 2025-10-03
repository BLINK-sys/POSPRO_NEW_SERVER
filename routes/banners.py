import os

from flask import Blueprint, request, jsonify, current_app
from extensions import db
from models.banner import Banner

banners_bp = Blueprint('banners', __name__)


# 🔹 Получить все баннеры
@banners_bp.route('/banners', methods=['GET'])
def get_banners():
    banners = Banner.query.order_by(Banner.order).all()
    return jsonify([{
        'id': b.id,
        'title': b.title,
        'subtitle': b.subtitle,
        'image': b.image,
        'order': b.order,
        'button_text': b.button_text,
        'button_link': b.button_link,
        'show_button': b.show_button,
        'active': b.active
    } for b in banners])


# 🔹 Добавить баннер
@banners_bp.route('/banners', methods=['POST'])
def add_banner():
    data = request.json

    # Найдём текущий максимальный order
    max_order = db.session.query(db.func.max(Banner.order)).scalar()
    next_order = (max_order + 1) if max_order is not None else 0

    banner = Banner(
        title=data.get('title'),
        subtitle=data.get('subtitle'),
        image=data.get('image'),
        order=next_order,
        active=data.get('active', True),
        button_text=data.get('button_text'),
        button_link=data.get('button_link'),
        show_button=data.get('show_button', False)
    )
    db.session.add(banner)
    db.session.commit()
    return jsonify({'message': 'Баннер создан', 'id': banner.id}), 201


# 🔹 Обновить баннер
@banners_bp.route('/banners/<int:banner_id>', methods=['PUT'])
def update_banner(banner_id):
    banner = Banner.query.get_or_404(banner_id)
    data = request.json
    banner.title = data.get('title', banner.title)
    banner.subtitle = data.get('subtitle', banner.subtitle)
    banner.image = data.get('image', banner.image)
    banner.order = data.get('order', banner.order)
    banner.active = data.get('active', banner.active)
    banner.button_text = data.get('button_text', banner.button_text)
    banner.button_link = data.get('button_link', banner.button_link)
    banner.show_button = data.get('show_button', banner.show_button)

    db.session.commit()
    return jsonify({'message': 'Баннер обновлён'})


@banners_bp.route('/banners/<int:banner_id>', methods=['DELETE'])
def delete_banner(banner_id):
    banner = Banner.query.get_or_404(banner_id)

    # Удаление файла изображения, если путь начинается с "/uploads/"
    if banner.image and banner.image.startswith('/uploads/'):
        try:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], banner.image.lstrip('/uploads/'))
            if os.path.exists(file_path):
                os.remove(file_path)

            # Удалить папку, если она пуста
            folder_path = os.path.dirname(file_path)
            if os.path.exists(folder_path) and not os.listdir(folder_path):
                os.rmdir(folder_path)

        except Exception as e:
            print(f"Ошибка при удалении изображения баннера: {e}")

    db.session.delete(banner)
    db.session.commit()
    return jsonify({'message': 'Баннер удалён'})


# 🔹 Обновить порядок баннеров
@banners_bp.route('/banners/reorder', methods=['POST'])
def reorder_banners():
    data = request.json
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список с объектами {id, order}'}), 400

    for item in data:
        banner = Banner.query.get(item.get('id'))
        if banner:
            banner.order = item.get('order', banner.order)

    db.session.commit()
    return jsonify({'message': 'Порядок баннеров обновлён'})
