"""
Скрипт для исправления таблицы order_items - добавление недостающего поля product_price
"""

from app import create_app
from extensions import db

app = create_app()

with app.app_context():
    try:
        # Проверяем текущую структуру таблицы
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('order_items')]
        print(f"Текущие столбцы в order_items: {columns}")
        
        # Если product_price отсутствует, добавляем его
        if 'product_price' not in columns:
            print("Добавляем недостающий столбец product_price...")
            db.engine.execute("""
                ALTER TABLE order_items 
                ADD COLUMN product_price DOUBLE PRECISION NOT NULL DEFAULT 0
            """)
            print("✅ Столбец product_price добавлен")
        else:
            print("✅ Столбец product_price уже существует")
            
        # Проверяем финальную структуру
        columns_after = [col['name'] for col in inspector.get_columns('order_items')]
        print(f"Финальные столбцы в order_items: {columns_after}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        
print("🎉 Готово!")
