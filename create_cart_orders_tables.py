"""
Скрипт для создания таблиц корзины и заказов в базе данных
"""

from app import create_app
from extensions import db
from models import Cart, Order, OrderItem

app = create_app()

with app.app_context():
    # Создаем таблицы
    db.create_all()
    print("✅ Таблицы корзины и заказов созданы успешно!")
    
    # Проверяем, что таблицы создались
    inspector = db.inspect(db.engine)
    tables = inspector.get_table_names()
    
    print("\n📋 Проверка созданных таблиц:")
    required_tables = ['cart', 'orders', 'order_items']
    
    for table in required_tables:
        if table in tables:
            print(f"✅ Таблица '{table}' создана")
            
            # Показываем структуру таблицы
            columns = inspector.get_columns(table)
            print(f"   Столбцы ({len(columns)}):")
            for col in columns:
                print(f"   - {col['name']}: {col['type']}")
            print()
        else:
            print(f"❌ Таблица '{table}' НЕ создана")
    
    print("🎉 Готово! Теперь можно использовать корзину и заказы.")
