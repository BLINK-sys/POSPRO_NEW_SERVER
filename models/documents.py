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
            # Проверяем, содержит ли имя файла искаженные символы
            if 'Ð' in self.filename:
                # Пытаемся исправить двойное кодирование
                try:
                    # Способ 1: UTF-8 → Latin1 → CP1251 → UTF-8
                    fixed = self.filename.encode('utf-8').decode('latin1').encode('cp1251').decode('utf-8')
                    print(f"Исправлено имя файла способом 1: {fixed}")
                    return fixed
                except Exception as e:
                    print(f"Способ 1 не сработал: {e}")
                
                try:
                    # Способ 2: Прямое декодирование как CP1251
                    fixed = self.filename.encode('latin1').decode('cp1251')
                    print(f"Исправлено имя файла способом 2: {fixed}")
                    return fixed
                except Exception as e:
                    print(f"Способ 2 не сработал: {e}")
                
                try:
                    # Способ 3: Через bytes
                    corrupted_bytes = self.filename.encode('utf-8')
                    latin1_decoded = corrupted_bytes.decode('latin1')
                    fixed = latin1_decoded.encode('cp1251').decode('utf-8')
                    print(f"Исправлено имя файла способом 3: {fixed}")
                    return fixed
                except Exception as e:
                    print(f"Способ 3 не сработал: {e}")
            
            # Если нет искаженных символов или исправление не удалось, возвращаем как есть
            return self.filename
            
        except UnicodeDecodeError:
            # Если не удалось декодировать, пытаемся исправить кодировку
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