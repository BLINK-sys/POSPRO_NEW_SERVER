from extensions import db


class ProductDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50))  # например, "doc", "driver", "manual"
    mime_type = db.Column(db.String(100))  # например, "application/pdf"
    
    @property
    def safe_filename(self):
        """Возвращает корректное имя файла (UTF-8 без перекодирования)"""
        try:
            # Если оно уже строка (str) — просто возвращаем как есть
            if isinstance(self.filename, bytes):
                return self.filename.decode('utf-8', errors='replace')
            return self.filename
        except Exception:
            return self.filename