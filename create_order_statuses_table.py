"""
Скрипт для создания таблицы статусов заказов и заполнения её дефолтными значениями
"""

from app import create_app
from extensions import db
from models import OrderStatus

app = create_app()

with app.app_context():
    # Создаем таблицы
    db.create_all()
    print("✅ Таблица order_statuses создана успешно!")
    
    # Проверяем, есть ли уже статусы
    existing_statuses = OrderStatus.query.count()
    if existing_statuses > 0:
        print(f"📋 В таблице уже есть {existing_statuses} статусов. Пропускаем заполнение.")
    else:
        # Создаем дефолтные статусы заказов
        default_statuses = [
            {
                'key': 'pending',
                'name': 'В ожидании',
                'description': 'Заказ ожидает подтверждения',
                'background_color': '#fef3c7',
                'text_color': '#92400e',
                'order': 1,
                'is_active': True,
                'is_final': False
            },
            {
                'key': 'confirmed',
                'name': 'Подтверждён',
                'description': 'Заказ подтверждён и принят в обработку',
                'background_color': '#dbeafe',
                'text_color': '#1e40af',
                'order': 2,
                'is_active': True,
                'is_final': False
            },
            {
                'key': 'processing',
                'name': 'В обработке',
                'description': 'Заказ обрабатывается',
                'background_color': '#fed7aa',
                'text_color': '#c2410c',
                'order': 3,
                'is_active': True,
                'is_final': False
            },
            {
                'key': 'shipped',
                'name': 'Отправлен',
                'description': 'Заказ отправлен клиенту',
                'background_color': '#e9d5ff',
                'text_color': '#7c3aed',
                'order': 4,
                'is_active': True,
                'is_final': False
            },
            {
                'key': 'delivered',
                'name': 'Доставлен',
                'description': 'Заказ успешно доставлен',
                'background_color': '#dcfce7',
                'text_color': '#166534',
                'order': 5,
                'is_active': True,
                'is_final': True
            },
            {
                'key': 'cancelled',
                'name': 'Отменён',
                'description': 'Заказ отменён',
                'background_color': '#fecaca',
                'text_color': '#dc2626',
                'order': 6,
                'is_active': True,
                'is_final': True
            }
        ]
        
        print("📝 Создаём дефолтные статусы заказов...")
        for status_data in default_statuses:
            status = OrderStatus(**status_data)
            db.session.add(status)
        
        db.session.commit()
        print(f"✅ Создано {len(default_statuses)} дефолтных статусов!")
    
    # Проверяем структуру таблицы
    inspector = db.inspect(db.engine)
    columns = inspector.get_columns('order_statuses')
    print(f"\n📋 Структура таблицы order_statuses ({len(columns)} столбцов):")
    for col in columns:
        print(f"   - {col['name']}: {col['type']}")
    
    # Показываем все статусы
    all_statuses = OrderStatus.query.order_by(OrderStatus.order).all()
    print(f"\n🏷️  Все статусы заказов ({len(all_statuses)}):")
    for status in all_statuses:
        print(f"   - {status.key}: {status.name} (цвета: {status.background_color}/{status.text_color})")
    
    print("\n🎉 Готово! Система статусов заказов настроена.")
