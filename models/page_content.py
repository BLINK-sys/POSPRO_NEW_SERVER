from extensions import db


class PageContent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    page = db.Column(db.String(50), unique=True)  # 'about' или 'contacts'
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
