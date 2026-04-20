import os
import re

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models import HelpArticle, HelpArticleMedia

help_articles_bp = Blueprint('help_articles', __name__)

VIDEO_EXTS = {'mp4', 'webm', 'mov'}


def _is_admin():
    role = (get_jwt() or {}).get('role')
    return role == 'admin'


def _sanitize_filename(filename):
    filename = (filename or '').replace(' ', '_')
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    return filename or 'video.mp4'


# ─── Список + деталь ──────────────────────────────────────
@help_articles_bp.route('/', methods=['GET'])
@jwt_required()
def list_articles():
    """Список карточек справки (доступ — любой авторизованный)."""
    articles = HelpArticle.query.order_by(HelpArticle.order, HelpArticle.id).all()
    return jsonify([a.to_dict() for a in articles])


@help_articles_bp.route('/<int:article_id>', methods=['GET'])
@jwt_required()
def get_article(article_id):
    article = HelpArticle.query.get_or_404(article_id)
    return jsonify(article.to_dict())


# ─── Создание / редактирование / удаление (только админ) ──
@help_articles_bp.route('/', methods=['POST'])
@jwt_required()
def create_article():
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Название обязательно'}), 400

    max_order = db.session.query(db.func.max(HelpArticle.order)).scalar() or 0
    article = HelpArticle(
        title=title,
        content=data.get('content') or '',
        order=max_order + 1,
    )
    db.session.add(article)
    db.session.commit()
    return jsonify(article.to_dict()), 201


@help_articles_bp.route('/<int:article_id>', methods=['PUT'])
@jwt_required()
def update_article(article_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    article = HelpArticle.query.get_or_404(article_id)
    data = request.get_json() or {}
    if 'title' in data:
        title = (data['title'] or '').strip()
        if not title:
            return jsonify({'error': 'Название обязательно'}), 400
        article.title = title
    if 'content' in data:
        article.content = data['content'] or ''
    db.session.commit()
    return jsonify(article.to_dict())


@help_articles_bp.route('/<int:article_id>', methods=['DELETE'])
@jwt_required()
def delete_article(article_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    article = HelpArticle.query.get_or_404(article_id)

    # Удаляем папку с файлами
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'help', str(article.id))
    if os.path.isdir(folder):
        import shutil
        try:
            shutil.rmtree(folder)
        except Exception as e:
            print(f'Не удалось удалить папку {folder}: {e}')

    db.session.delete(article)
    db.session.commit()
    return jsonify({'message': 'Удалено'})


# ─── Сортировка карточек ──────────────────────────────────
@help_articles_bp.route('/reorder', methods=['PUT'])
@jwt_required()
def reorder_articles():
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    data = request.get_json() or {}
    ids = data.get('ids') or data.get('article_ids') or []
    if not isinstance(ids, list):
        return jsonify({'error': 'Неверный формат данных'}), 400

    for index, article_id in enumerate(ids):
        art = HelpArticle.query.get(article_id)
        if art:
            art.order = index + 1
    db.session.commit()
    return jsonify({'message': 'Порядок обновлён'})


# ─── Загрузка / удаление видео ────────────────────────────
@help_articles_bp.route('/<int:article_id>/videos', methods=['POST'])
@jwt_required()
def upload_video(article_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    article = HelpArticle.query.get_or_404(article_id)

    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'Файл не передан'}), 400

    filename = _sanitize_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in VIDEO_EXTS:
        return jsonify({'error': f'Разрешены только видео: {", ".join(VIDEO_EXTS)}'}), 400

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'help', str(article.id))
    os.makedirs(folder, exist_ok=True)

    # Обработка коллизий имён
    base_path = os.path.join(folder, filename)
    if os.path.exists(base_path):
        name_part, ext_part = os.path.splitext(filename)
        i = 1
        while os.path.exists(os.path.join(folder, f'{name_part}_{i}{ext_part}')):
            i += 1
        filename = f'{name_part}_{i}{ext_part}'

    file.save(os.path.join(folder, filename))

    max_order = (
        db.session.query(db.func.max(HelpArticleMedia.order))
        .filter(HelpArticleMedia.article_id == article.id)
        .scalar()
        or 0
    )
    media = HelpArticleMedia(
        article_id=article.id,
        url=f'/uploads/help/{article.id}/{filename}',
        filename=filename,
        order=max_order + 1,
    )
    db.session.add(media)
    db.session.commit()

    return jsonify(media.to_dict()), 201


@help_articles_bp.route('/videos/<int:media_id>', methods=['DELETE'])
@jwt_required()
def delete_video(media_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    media = HelpArticleMedia.query.get_or_404(media_id)

    # Удалить файл с диска
    if media.url and media.url.startswith('/uploads/'):
        rel = media.url[len('/uploads/'):]
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], rel)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f'Не удалось удалить файл {file_path}: {e}')

    db.session.delete(media)
    db.session.commit()
    return jsonify({'message': 'Удалено'})


@help_articles_bp.route('/<int:article_id>/videos/reorder', methods=['PUT'])
@jwt_required()
def reorder_videos(article_id):
    if not _is_admin():
        return jsonify({'error': 'Только администратор'}), 403

    data = request.get_json() or {}
    ids = data.get('ids') or []
    for index, media_id in enumerate(ids):
        m = HelpArticleMedia.query.get(media_id)
        if m and m.article_id == article_id:
            m.order = index + 1
    db.session.commit()
    return jsonify({'message': 'Порядок обновлён'})
