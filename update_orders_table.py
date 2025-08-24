"""
Скрипт для обновления таблицы orders - добавление поля status_id
"""

from app import create_app
from extensions import db
from models import Order, OrderStatus

app = create_app()

with app.app_context():
    try:
        # Проверяем, есть ли уже столбец status_id
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('orders')]
        
        if 'status_id' not in columns:
            print("Добавляем столбец status_id в таблицу orders...")
            with db.engine.connect() as conn:
                conn.execute(db.text("""
                    ALTER TABLE orders 
                    ADD COLUMN status_id INTEGER
                """))
                conn.commit()
            print("✅ Столбец status_id добавлен")
        else:
            print("✅ Столбец status_id уже существует")
        
        # Создаем внешний ключ
        try:
            print("Создаём внешний ключ для status_id...")
            with db.engine.connect() as conn:
                conn.execute(db.text("""
                    ALTER TABLE orders 
                    ADD FOREIGN KEY (status_id) REFERENCES order_statuses(id)
                """))
                conn.commit()
            print("✅ Внешний ключ создан")
        except Exception as e:
            print(f"⚠️  Внешний ключ уже существует или ошибка: {e}")
        
        # Обновляем существующие заказы, устанавливая status_id на основе status
        print("Обновляем существующие заказы...")
        
        # Получаем все статусы
        statuses = {status.key: status.id for status in OrderStatus.query.all()}
        print(f"Найдено статусов: {statuses}")
        
        # Обновляем заказы
        orders = Order.query.filter(Order.status_id.is_(None)).all()
        updated_count = 0
        
        for order in orders:
            if order.status in statuses:
                order.status_id = statuses[order.status]
                updated_count += 1
        
        if updated_count > 0:
            db.session.commit()
            print(f"✅ Обновлено {updated_count} заказов")
        else:
            print("📋 Все заказы уже имеют правильный status_id")
        
        # Проверяем результат
        all_orders = Order.query.all()
        orders_with_status_info = [o for o in all_orders if o.status_id is not None]
        
        print(f"\n📊 Статистика:")
        print(f"   Всего заказов: {len(all_orders)}")
        print(f"   С status_id: {len(orders_with_status_info)}")
        
        # Проверяем финальную структуру
        columns_after = [col['name'] for col in inspector.get_columns('orders')]
        print(f"\n📋 Финальные столбцы в orders: {len(columns_after)}")
        for col in columns_after:
            print(f"   - {col}")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        db.session.rollback()

print("\n🎉 Готово!")
