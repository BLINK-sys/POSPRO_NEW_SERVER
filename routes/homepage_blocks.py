from flask import Blueprint, request, jsonify
from extensions import db
from models.homepage_block import HomepageBlock
from models.homepage_block_title import HomepageBlockItem

homepage_blocks_bp = Blueprint('homepage_blocks', __name__)


@homepage_blocks_bp.route('/homepage-blocks', methods=['GET'])
def get_all_blocks():
    blocks = HomepageBlock.query.order_by(HomepageBlock.order).all()
    result = []
    for block in blocks:
        items = HomepageBlockItem.query.filter_by(block_id=block.id).order_by(HomepageBlockItem.order).all()
        result.append({
            'id': block.id,
            'title': block.title,
            'description': block.description,
            'type': block.type,
            'active': block.active,
            'order': block.order,
            'carusel': block.carusel,
            'show_title': block.show_title,
            'title_align': block.title_align,
            'background_color': block.background_color,
            'show_products_categories_filter': block.show_products_categories_filter,
            'items': [item.item_id for item in items]
        })
    return jsonify(result)


@homepage_blocks_bp.route('/homepage-blocks', methods=['POST'])
def create_block():
    data = request.json
    title = data.get('title')
    description = data.get('description')
    type_ = data.get('type')
    active = data.get('active', True)
    order = data.get('order', 0)
    carusel = data.get('carusel', False)
    show_title = data.get('show_title', True)
    title_align = data.get('title_align', 'left')
    background_color = data.get('background_color') or None  # '' → NULL
    show_products_categories_filter = data.get('show_products_categories_filter', True)
    item_ids = data.get('items', [])

    block = HomepageBlock(
        title=title,
        description=description,
        type=type_,
        active=active,
        order=order,
        carusel=carusel,
        show_title=show_title,
        title_align=title_align,
        background_color=background_color,
        show_products_categories_filter=show_products_categories_filter,
    )
    db.session.add(block)
    db.session.flush()

    for idx, item_id in enumerate(item_ids):
        db.session.add(HomepageBlockItem(block_id=block.id, item_id=item_id, order=idx))

    db.session.commit()
    return jsonify({'message': 'Блок создан', 'id': block.id})


@homepage_blocks_bp.route('/homepage-blocks/<int:block_id>', methods=['PUT'])
def update_block(block_id):
    data = request.json
    block = HomepageBlock.query.get_or_404(block_id)

    block.title = data.get('title', block.title)
    block.description = data.get('description', block.description)
    block.type = data.get('type', block.type)
    block.active = data.get('active', block.active)
    block.order = data.get('order', block.order)
    block.carusel = data.get('carusel', block.carusel)
    block.show_title = data.get('show_title', block.show_title)
    block.title_align = data.get('title_align', block.title_align)
    if 'background_color' in data:
        # Явно позволяем передать '' / None для сброса на дефолт.
        val = data.get('background_color')
        block.background_color = val if val else None
    if 'show_products_categories_filter' in data:
        block.show_products_categories_filter = bool(data.get('show_products_categories_filter'))

    # Items трогаем ТОЛЬКО если ключ явно передан. Раньше делали
    # безусловно — частичный PATCH (например, тумблер фильтра категорий
    # на витрине) обнулял привязки товаров.
    if 'items' in data:
        HomepageBlockItem.query.filter_by(block_id=block.id).delete()
        for idx, item_id in enumerate(data.get('items') or []):
            db.session.add(HomepageBlockItem(block_id=block.id, item_id=item_id, order=idx))

    db.session.commit()
    return jsonify({'message': 'Блок обновлён'})


# 🔹 Удалить блок
@homepage_blocks_bp.route('/homepage-blocks/<int:block_id>', methods=['DELETE'])
def delete_block(block_id):
    HomepageBlockItem.query.filter_by(block_id=block_id).delete()
    HomepageBlock.query.filter_by(id=block_id).delete()
    db.session.commit()
    return jsonify({'message': 'Блок удалён'})


# 🔹 Изменить статус (вкл/выкл)
@homepage_blocks_bp.route('/homepage-blocks/<int:block_id>/toggle', methods=['PATCH'])
def toggle_block(block_id):
    block = HomepageBlock.query.get_or_404(block_id)
    block.active = not block.active
    db.session.commit()
    return jsonify({'message': f'Блок {"включён" if block.active else "отключён"}'})


# 🔹 Изменить порядок блоков
@homepage_blocks_bp.route('/homepage-blocks/reorder', methods=['POST'])
def reorder_blocks():
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список с id и order'}), 400

    for entry in data:
        block = HomepageBlock.query.get(entry.get('id'))
        if block:
            block.order = entry.get('order', block.order)

    db.session.commit()
    return jsonify({'message': 'Порядок блоков обновлён'})


# 🔹 Изменить порядок элементов в блоке
@homepage_blocks_bp.route('/homepage-blocks/<int:block_id>/items/reorder', methods=['POST'])
def reorder_block_items(block_id):
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список с id и order'}), 400

    for entry in data:
        item = HomepageBlockItem.query.filter_by(
            block_id=block_id,
            item_id=entry.get('id')
        ).first()
        if item:
            item.order = entry.get('order', item.order)

    db.session.commit()
    return jsonify({'message': 'Порядок элементов блока обновлён'})
