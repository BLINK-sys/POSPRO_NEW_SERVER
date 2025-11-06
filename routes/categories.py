import os
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from extensions import db
from models.category import Category

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/', methods=['GET'])
def get_categories():
    categories = Category.query.order_by(Category.parent_id, Category.order).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'description': c.description,
        'image_url': c.image_url,
        'parent_id': c.parent_id,
        'order': c.order,
        'show_in_menu': c.show_in_menu
    } for c in categories])


@categories_bp.route('/with-image', methods=['POST'])
def create_category_with_image():
    name = request.form.get('name')
    slug = request.form.get('slug')
    description = request.form.get('description')
    parent_id = request.form.get('parent_id')
    file = request.files.get('file')

    # Проверка обязательных полей
    if not name or not slug:
        return jsonify({'error': 'name and slug are required'}), 400

    show_in_menu = request.form.get('show_in_menu', 'true').lower() == 'true'
    category = Category(
        name=name,
        slug=slug,
        description=description,
        parent_id=parent_id if parent_id else None,
        show_in_menu=show_in_menu
    )
    db.session.add(category)
    db.session.flush()  # Получаем ID до коммита

    if file:
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        ext = os.path.splitext(filename)[1]
        final_filename = f"{timestamp}{ext}"
        folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'categories', str(category.id))
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, final_filename)
        file.save(file_path)
        category.image_url = f'/uploads/categories/{category.id}/{final_filename}'

    db.session.commit()

    return jsonify({
        'id': category.id,
        'name': category.name,
        'slug': category.slug,
        'description': category.description,
        'image_url': category.image_url,
        'parent_id': category.parent_id,
        'order': category.order,
        'show_in_menu': category.show_in_menu
    }), 201


@categories_bp.route('/<int:category_id>', methods=['PUT'])
def update_category(category_id):
    category = Category.query.get_or_404(category_id)
    data = request.json
    category.name = data['name']
    category.slug = data['slug']
    category.description = data.get('description')
    category.image_url = data.get('image_url')
    category.parent_id = data.get('parent_id')
    
    if 'show_in_menu' in data:
        new_show_in_menu = bool(data['show_in_menu'])
        category.show_in_menu = new_show_in_menu
        
        # Если категория отключается, отключаем все дочерние категории рекурсивно
        if not new_show_in_menu:
            def disable_children(parent_id):
                children = Category.query.filter_by(parent_id=parent_id).all()
                for child in children:
                    child.show_in_menu = False
                    disable_children(child.id)
            disable_children(category_id)
    
    db.session.commit()
    return jsonify(category.to_dict())


@categories_bp.route('/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    
    # Рекурсивно удаляем все дочерние категории
    def delete_children_recursive(parent_id):
        children = Category.query.filter_by(parent_id=parent_id).all()
        for child in children:
            # Сначала удаляем всех внуков и т.д.
            delete_children_recursive(child.id)
            # Затем удаляем саму дочернюю категорию
            db.session.delete(child)
    
    # Удаляем все дочерние категории
    delete_children_recursive(category_id)
    
    # Удаляем саму категорию
    db.session.delete(category)
    db.session.commit()
    return jsonify({'message': 'Category deleted'})


@categories_bp.route('/reorder', methods=['POST'])
def reorder_categories():
    data = request.get_json()

    if not isinstance(data, list):
        return jsonify({'error': 'Invalid data format'}), 400

    for item in data:
        category_id = item.get('id')
        order = item.get('order')

        if category_id is None or order is None:
            continue

        category = Category.query.get(category_id)
        if category:
            category.order = order

    db.session.commit()
    return jsonify({'message': 'Category order updated'}), 200
