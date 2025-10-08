"""
Административные маршруты для настройки системы
"""

from flask import Blueprint, jsonify
from extensions import db
from utils.jwt import token_required, admin_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

admin_setup_bp = Blueprint('admin_setup', __name__)

@admin_setup_bp.route('/api/admin/setup/characteristics', methods=['POST'])
@token_required
@admin_required
def setup_characteristics_table(current_user):
    """Создать таблицу characteristics_list (только для админов)"""
    try:
        with db.engine.connect() as connection:
            # SQL для создания таблицы characteristics_list
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS characteristics_list (
                id SERIAL PRIMARY KEY,
                characteristic_key VARCHAR(100) NOT NULL UNIQUE,
                unit_of_measurement VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
            
            # Выполняем создание таблицы
            connection.execute(text(create_table_sql))
            connection.commit()
            
            # Добавляем начальные данные
            insert_data_sql = """
            INSERT INTO characteristics_list (characteristic_key, unit_of_measurement) VALUES
            ('ВЕС', 'кг'),
            ('ДЛИНА', 'см'),
            ('ШИРИНА', 'см'),
            ('ВЫСОТА', 'см'),
            ('ОБЪЕМ', 'л'),
            ('МОЩНОСТЬ', 'Вт'),
            ('НАПРЯЖЕНИЕ', 'В'),
            ('ТОК', 'А'),
            ('ЧАСТОТА', 'Гц'),
            ('ТЕМПЕРАТУРА', '°C')
            ON CONFLICT (characteristic_key) DO NOTHING;
            """
            
            connection.execute(text(insert_data_sql))
            connection.commit()
            
            return jsonify({
                'success': True,
                'message': 'Таблица characteristics_list успешно создана и заполнена данными'
            }), 200
            
    except SQLAlchemyError as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка базы данных: {str(e)}'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании таблицы: {str(e)}'
        }), 500
