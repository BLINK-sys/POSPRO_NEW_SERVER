"""
Модели для конфигурации страницы поиска (`/search`).

Когда юзер заходит на /search и ещё ничего не ввёл — показываем
панельку с табами «Категории» и «Бренды», содержимое которых курируется
админом отдельно от главной/каталога.

Структура:
  - SearchPageSettings — single-row таблица с тоглами включения каждого
    таба. Если оба выключены, фронт вообще не показывает панель.
  - SearchPageCategory — упорядоченный список категорий для таба
    «Категории». UNIQUE по category_id, чтобы нельзя было добавить
    одну и ту же дважды.
  - SearchPageBrand — упорядоченный список брендов для таба «Бренды».
    UNIQUE по brand_id.

Принцип повторяет HomepageCategory / SystemBrand, но отдельный набор
таблиц намеренно — чтобы конфигурация поиска не пересекалась с главной.
"""

from extensions import db
from datetime import datetime


class SearchPageSettings(db.Model):
    __tablename__ = 'search_page_settings'

    id = db.Column(db.Integer, primary_key=True)
    categories_enabled = db.Column(db.Boolean, nullable=False, default=True)
    brands_enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'categories_enabled': bool(self.categories_enabled),
            'brands_enabled': bool(self.brands_enabled),
        }


class SearchPageCategory(db.Model):
    __tablename__ = 'search_page_categories'

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id', ondelete='CASCADE'), nullable=False, unique=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SearchPageBrand(db.Model):
    __tablename__ = 'search_page_brands'

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id', ondelete='CASCADE'), nullable=False, unique=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
