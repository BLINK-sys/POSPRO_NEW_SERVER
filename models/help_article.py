from datetime import datetime

from extensions import db


class HelpArticle(db.Model):
    """Карточка справки (инструкция) для админов"""
    __tablename__ = 'help_articles'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, default='')  # HTML от TipTap
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    media = db.relationship(
        'HelpArticleMedia',
        backref='article',
        cascade='all, delete-orphan',
        order_by='HelpArticleMedia.order',
    )

    def to_dict(self, include_media=True):
        d = {
            'id': self.id,
            'title': self.title,
            'content': self.content or '',
            'order': self.order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_media:
            d['media'] = [m.to_dict() for m in self.media]
        return d


class HelpArticleMedia(db.Model):
    """Видео, прикреплённое к карточке справки"""
    __tablename__ = 'help_article_media'

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('help_articles.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(255))
    order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            'id': self.id,
            'article_id': self.article_id,
            'url': self.url,
            'filename': self.filename,
            'order': self.order,
        }
