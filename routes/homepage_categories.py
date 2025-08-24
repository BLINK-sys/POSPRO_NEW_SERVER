from flask import Blueprint, request, jsonify
from extensions import db
from models.homepage_categories import HomepageCategory
from models.category import Category

homepage_categories_bp = Blueprint('homepage_categories', __name__)


# 🔹 Получить список выбранных категорий для главной
@homepage_categories_bp.route('/homepage-categories', methods=['GET'])
def get_homepage_categories():
    categories = HomepageCategory.query.order_by(HomepageCategory.order).all()
    return jsonify([c.category_id for c in categories])


# 🔹 Обновить список выбранных категорий (с очисткой)
@homepage_categories_bp.route('/homepage-categories', methods=['PUT'])
def update_homepage_categories():
    data = request.get_json()

    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список ID категорий'}), 400

    HomepageCategory.query.delete()

    for idx, category_id in enumerate(data):
        new_entry = HomepageCategory(category_id=category_id, order=idx)
        db.session.add(new_entry)

    db.session.commit()
    return jsonify({'message': 'Категории обновлены'})


# 🔹 Обновить порядок категорий (без удаления)
@homepage_categories_bp.route('/homepage-categories/reorder', methods=['POST'])
def reorder_homepage_categories():
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список объектов с category_id и order'}), 400

    for item in data:
        if not isinstance(item, dict) or 'category_id' not in item or 'order' not in item:
            continue  # пропустить некорректные

        category = HomepageCategory.query.filter_by(category_id=item['category_id']).first()
        if category:
            category.order = item['order']

    db.session.commit()
    return jsonify({'message': 'Порядок категорий обновлён'})


# 🔹 Получить список всех категорий
@homepage_categories_bp.route('/homepage-categories/all', methods=['GET'])
def get_all_categories():
    categories = Category.query.order_by(Category.order).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'parent_id': c.parent_id,
        'description': c.description,
        'image_url': c.image_url,
        'order': c.order
    } for c in categories])
