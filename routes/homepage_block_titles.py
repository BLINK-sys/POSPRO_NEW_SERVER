# routes/homepage_block_titles.py

from flask import Blueprint, jsonify, request
from extensions import db
from models.homepage_block import HomepageBlock

homepage_block_titles_bp = Blueprint('homepage_block_titles', __name__)


# 🔹 Получить все названия блоков
@homepage_block_titles_bp.route('/homepage-block-titles', methods=['GET'])
def get_all_block_titles():
    titles = HomepageBlock.query.all()
    return jsonify([{
        'id': t.id,
        'slug': t.slug,
        'title': t.title
    } for t in titles])


# 🔹 Получить одно название по slug
@homepage_block_titles_bp.route('/homepage-block-titles/<string:slug>', methods=['GET'])
def get_block_title(slug):
    title = HomepageBlock.query.filter_by(slug=slug).first()
    if not title:
        return jsonify({'title': ''}), 404
    return jsonify({'title': title.title})


# 🔹 Обновить или создать заголовок по slug
@homepage_block_titles_bp.route('/homepage-block-titles/<string:slug>', methods=['PUT'])
def update_block_title(slug):
    data = request.get_json()
    new_title = data.get('title', '')

    if not new_title:
        return jsonify({'error': 'title is required'}), 400

    block = HomepageBlock.query.filter_by(slug=slug).first()
    if not block:
        block = HomepageBlock(slug=slug, title=new_title)
        db.session.add(block)
    else:
        block.title = new_title

    db.session.commit()
    return jsonify({'message': f'Заголовок блока "{slug}" обновлён'})



