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


@categories_bp.route('/<int:category_id>', methods=['GET'])
def get_category(category_id):
    category = Category.query.get_or_404(category_id)
    return jsonify(category.to_dict())


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
    try:
        from models.product import Product
        from models.homepage_categories import HomepageCategory
        
        category = Category.query.get_or_404(category_id)
        
        # Шаг 1: Собираем все ID категорий, которые будут удалены (включая дочерние)
        categories_to_delete = [category_id]
        
        def collect_children_recursive(parent_id):
            children = Category.query.filter_by(parent_id=parent_id).all()
            for child in children:
                categories_to_delete.append(child.id)
                collect_children_recursive(child.id)
        
        collect_children_recursive(category_id)
        
        # Шаг 2: Обрабатываем товары - устанавливаем category_id в NULL для всех товаров
        # в удаляемых категориях (включая родительскую и все дочерние)
        products_count = 0
        if categories_to_delete:
            products_count = Product.query.filter(Product.category_id.in_(categories_to_delete)).count()
            if products_count > 0:
                # Устанавливаем category_id в NULL для всех товаров
                Product.query.filter(Product.category_id.in_(categories_to_delete)).update(
                    {Product.category_id: None}, 
                    synchronize_session=False
                )
        
        # Шаг 3: Удаляем записи из homepage_categories
        if categories_to_delete:
            HomepageCategory.query.filter(HomepageCategory.category_id.in_(categories_to_delete)).delete(synchronize_session=False)
        
        # Шаг 4: Рекурсивно удаляем все дочерние категории (снизу вверх)
        # Сначала удаляем самые глубокие (листья), потом поднимаемся вверх к родителю
        
        def delete_children_recursive(parent_id):
            # Получаем прямых детей этой категории
            children = Category.query.filter_by(parent_id=parent_id).all()
            for child in children:
                # Сначала рекурсивно удаляем всех внуков и т.д. (уходим вглубь)
                delete_children_recursive(child.id)
                # После удаления всех потомков удаляем саму дочернюю категорию
                # Обновляем parent_id у любых оставшихся дочерних (на всякий случай)
                Category.query.filter(Category.parent_id == child.id).update(
                    {Category.parent_id: None},
                    synchronize_session=False
                )
                # Удаляем саму дочернюю категорию
                Category.query.filter(Category.id == child.id).delete(synchronize_session=False)
                db.session.flush()  # Применяем удаление сразу
        
        # Удаляем все дочерние категории рекурсивно
        delete_children_recursive(category_id)
        
        # Шаг 5: Удаляем саму родительскую категорию
        # Обновляем parent_id у любых оставшихся дочерних (на всякий случай)
        Category.query.filter(Category.parent_id == category_id).update(
            {Category.parent_id: None},
            synchronize_session=False
        )
        # Удаляем саму категорию
        Category.query.filter(Category.id == category_id).delete(synchronize_session=False)
        
        # Коммитим все изменения
        db.session.commit()
        
        message = 'Category deleted'
        if products_count > 0:
            message += f'. {products_count} product(s) were moved to uncategorized'
        
        return jsonify({'message': message}), 200
    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error deleting category {category_id}: {error_details}")
        return jsonify({'error': f'Ошибка при удалении категории: {str(e)}', 'details': error_details}), 500


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
