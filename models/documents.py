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
        """Возвращает безопасное имя файла с правильной кодировкой"""
        try:
            # Пытаемся декодировать как UTF-8
            return self.filename
        except UnicodeDecodeError:
            # Если не удалось, пытаемся исправить кодировку
            try:
                # Пробуем разные кодировки
                for encoding in ['cp1251', 'latin1', 'iso-8859-1']:
                    try:
                        return self.filename.encode(encoding).decode('utf-8')
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        continue
                # Если ничего не помогло, возвращаем как есть
                return self.filename
            except Exception:
                return self.filename