# routes/benefits.py

from flask import Blueprint, request, jsonify
from extensions import db
from models.benefit import Benefit

benefits_bp = Blueprint('benefits', __name__)


# 🔹 Получить список преимуществ
@benefits_bp.route('/benefits', methods=['GET'])
def get_benefits():
    benefits = Benefit.query.order_by(Benefit.order).all()
    return jsonify([{
        'id': b.id,
        'icon': b.icon,
        'title': b.title,
        'description': b.description,
        'order': b.order
    } for b in benefits])


# 🔹 Добавить новое преимущество
@benefits_bp.route('/benefits', methods=['POST'])
def create_benefit():
    data = request.get_json()
    benefit = Benefit(
        icon=data.get('icon'),
        title=data.get('title'),
        description=data.get('description'),
        order=data.get('order', 0)
    )
    db.session.add(benefit)
    db.session.commit()
    return jsonify({'message': 'Преимущество добавлено', 'id': benefit.id})


# 🔹 Обновить преимущество
@benefits_bp.route('/benefits/<int:benefit_id>', methods=['PUT'])
def update_benefit(benefit_id):
    benefit = Benefit.query.get_or_404(benefit_id)
    data = request.get_json()

    benefit.icon = data.get('icon', benefit.icon)
    benefit.title = data.get('title', benefit.title)
    benefit.description = data.get('description', benefit.description)
    benefit.order = data.get('order', benefit.order)

    db.session.commit()
    return jsonify({'message': 'Преимущество обновлено'})


# 🔹 Удалить преимущество
@benefits_bp.route('/benefits/<int:benefit_id>', methods=['DELETE'])
def delete_benefit(benefit_id):
    benefit = Benefit.query.get_or_404(benefit_id)
    db.session.delete(benefit)
    db.session.commit()
    return jsonify({'message': 'Преимущество удалено'})


# 🔹 Обновить порядок преимуществ
@benefits_bp.route('/benefits/reorder', methods=['POST'])
def reorder_benefits():
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Ожидается список объектов с id и order'}), 400

    for item in data:
        benefit = Benefit.query.get(item.get('id'))
        if benefit and 'order' in item:
            benefit.order = item['order']

    db.session.commit()
    return jsonify({'message': 'Порядок преимуществ обновлён'})
