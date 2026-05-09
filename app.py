from flask import Flask, send_from_directory, send_file
from flask_cors import CORS
from config import Config
from extensions import db, jwt
from routes.auth import auth_bp
from routes.banners import banners_bp
from routes.benefits import benefits_bp
from routes.categories import categories_bp
from routes.clients_routes import clients_bp
from routes.footer_settings import footer_settings_bp
from routes.homepage_block_titles import homepage_block_titles_bp
from routes.homepage_blocks import homepage_blocks_bp
from routes.homepage_categories import homepage_categories_bp
from routes.products import products_bp
from routes.characteristics import characteristics_bp
from routes.characteristics_list import characteristics_list_bp
from routes.profile import profile_bp
from routes.public_homepage import public_homepage_bp
from routes.small_banners import small_banner_bp
from routes.system_brands import system_brands_bp
from routes.system_users import system_users_bp
from routes.upload import upload_bp
from routes.brands_statuses import bp as brands_statuses_bp
from routes.suppliers import suppliers_bp
import os

from routes.upload_admin import upload_admin_bp
from routes.favorites import favorites_bp
from routes.cart import cart_bp
from routes.orders import orders_bp
from routes.kp_settings import kp_settings_bp
from routes.kp_history import kp_history_bp
from routes.kp_share import kp_share_bp
from routes.kp_clients import kp_clients_bp
from routes.search_page import search_page_bp
from routes.kp_logos import kp_logos_bp
from routes.dashboard import dashboard_bp
from routes.catalog_visibility import catalog_visibility_bp
from routes.currencies import currencies_bp
from routes.warehouses import warehouses_bp
from routes.product_costs import product_costs_bp
from routes.order_statuses import order_statuses_bp
from routes.product_availability_statuses import product_availability_statuses_bp
from routes.public_product_availability_statuses import public_product_availability_statuses_bp
from routes.help_articles import help_articles_bp
from routes.drivers import drivers_bp
from routes.ai_consultant_access import ai_consultant_access_bp
from routes.ai_logs import ai_logs_bp
from routes.product_auto_fill import product_auto_fill_bp
from models.systemuser import SystemUser


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app)

    db.init_app(app)
    jwt.init_app(app)

    # 🔹 Категории, товары, характеристики
    app.register_blueprint(categories_bp, url_prefix="/categories")  # /categories/*
    app.register_blueprint(products_bp, url_prefix="/products")  # /products/*
    app.register_blueprint(characteristics_bp, url_prefix="/characteristics")  # /characteristics/*
    app.register_blueprint(characteristics_list_bp, url_prefix="/characteristics-list")  # /characteristics-list/*

    # 🔹 Загрузка файлов и медиа
    app.register_blueprint(upload_bp, url_prefix='/upload')  # /upload/*

    # 🔹 Метаданные (статусы, бренды и пр.)
    app.register_blueprint(brands_statuses_bp, url_prefix='/meta')  # /meta/*
    
    # 🔹 Справочник поставщиков
    app.register_blueprint(suppliers_bp, url_prefix='/meta/suppliers')  # /meta/suppliers/*

    # 🔹 Аутентификация и сессии
    app.register_blueprint(auth_bp, url_prefix='/auth')  # /auth/login, /auth/me и т.д.

    # 🔹 Системные пользователи (админка)
    app.register_blueprint(system_users_bp, url_prefix='/api')  # /api/system-users/*

    # 🔹 Клиенты (физ лица, ИП, ТОО)
    app.register_blueprint(clients_bp)  # /clients/*

    # 🔹 Профиль пользователя
    app.register_blueprint(profile_bp)  # /api/profile
    
    # 🔹 Избранное
    app.register_blueprint(favorites_bp, url_prefix='/api')  # /api/favorites
    
    # 🔹 Корзина
    app.register_blueprint(cart_bp, url_prefix='/api')  # /api/cart
    
    # 🔹 Заказы
    app.register_blueprint(orders_bp, url_prefix='/api')  # /api/orders

    # 🔹 Настройки КП
    app.register_blueprint(kp_settings_bp, url_prefix='/api')  # /api/kp-settings
    app.register_blueprint(kp_history_bp, url_prefix='/api')   # /api/kp-history
    app.register_blueprint(kp_share_bp, url_prefix='/api')     # /api/kp-history/<id>/share, /api/admin/kp-super-admin-access
    app.register_blueprint(kp_clients_bp, url_prefix='/api')   # /api/kp-clients
    app.register_blueprint(search_page_bp, url_prefix='/api')  # /api/public/search-page, /api/admin/search-page/*
    app.register_blueprint(kp_logos_bp, url_prefix='/api')     # /api/kp-logos

    # 🔹 Доступ к AI Консультанту (страница /ai)
    app.register_blueprint(ai_consultant_access_bp, url_prefix='/api')
    # /api/ai-consultant/access (public), /api/product-import/access (system),
    # /api/admin/ai-consultant/settings (owner)

    # 🔹 AI-парсинг страницы товара донора (POST /api/admin/products/auto-fill)
    app.register_blueprint(product_auto_fill_bp, url_prefix='/api')

    # 🔹 Логи AI-фич: импорт товаров и чат консультанта
    app.register_blueprint(ai_logs_bp, url_prefix='/api')

    # 🔹 Видимость каталогов (публичный + админский под /api)
    app.register_blueprint(catalog_visibility_bp, url_prefix='/api')  # /api/catalog-visibility, /api/admin-catalog-visibility
    
    # 🔹 Статусы заказов
    app.register_blueprint(order_statuses_bp, url_prefix='/api/admin')  # /api/admin/order-statuses
    
    # 🔹 Статусы наличия товара (админка)
    app.register_blueprint(product_availability_statuses_bp, url_prefix='/api/admin')  # /api/admin/product-availability-statuses
    
    # 🔹 Статусы наличия товара (публичные)
    app.register_blueprint(public_product_availability_statuses_bp, url_prefix='/api')  # /api/product-availability-statuses/check/*

    # 🔹 Справка (инструкции для админов/менеджеров)
    app.register_blueprint(help_articles_bp, url_prefix='/api/help-articles')  # /api/help-articles/*

    # 🔹 Мастер-список драйверов (переиспользуемых в нескольких товарах)
    app.register_blueprint(drivers_bp, url_prefix='/api/drivers')  # /api/drivers/*

    # 🔹 Главная страница (настройки, категории, баннеры, преимущества и пр.)
    app.register_blueprint(homepage_categories_bp, url_prefix='/api/admin')  # /api/admin/homepage-categories
    app.register_blueprint(banners_bp, url_prefix='/api/admin')  # /api/admin/banners/*
    app.register_blueprint(benefits_bp, url_prefix='/api/admin')  # /api/admin/benefits/*
    app.register_blueprint(upload_admin_bp, url_prefix='/api/admin')  # /api/admin/benefits/*
    app.register_blueprint(system_brands_bp, url_prefix='/api/admin')
    app.register_blueprint(footer_settings_bp, url_prefix='/api')
    app.register_blueprint(homepage_block_titles_bp, url_prefix='/api/admin')
    app.register_blueprint(homepage_blocks_bp, url_prefix='/api/admin')
    app.register_blueprint(small_banner_bp, url_prefix='/api/admin')

    app.register_blueprint(public_homepage_bp, url_prefix='/api')

    # 🔹 Дашборд (трекинг + статистика)
    app.register_blueprint(dashboard_bp, url_prefix='/api')  # /api/track-visit, /api/track-request, /api/dashboard-stats

    # 🔹 Склады, валюты, себестоимость
    app.register_blueprint(currencies_bp, url_prefix='/meta/currencies')  # /meta/currencies/*
    app.register_blueprint(warehouses_bp, url_prefix='/meta/warehouses')  # /meta/warehouses/*
    app.register_blueprint(product_costs_bp, url_prefix='/meta/product-costs')  # /meta/product-costs/*

    # Настройки загрузки файлов берутся из Config
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
    app.config['ALLOWED_EXTENSIONS'] = Config.ALLOWED_EXTENSIONS
    app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

    # Создаём папку для загрузок при первом запуске
    print(f"Creating uploads folder: {app.config['UPLOAD_FOLDER']}")
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    with app.app_context():
        db.create_all()

        # Безопасное добавление новых столбцов в существующие таблицы
        try:
            db.session.execute(db.text(
                "ALTER TABLE site_requests ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(255)"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция site_requests: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE product_views ADD COLUMN IF NOT EXISTS view_type VARCHAR(20) DEFAULT 'detail'"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция product_views: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE warehouse_variable ALTER COLUMN label TYPE TEXT"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция warehouse_variable.label: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE warehouse_formula ADD COLUMN IF NOT EXISTS delivery_formula TEXT"
            ))
            db.session.execute(db.text(
                "ALTER TABLE product_warehouse_cost ADD COLUMN IF NOT EXISTS calculated_delivery FLOAT"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция delivery formula: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE kp_history ADD COLUMN IF NOT EXISTS calculator_data JSON"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция kp_history calculator_data: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE warehouse ADD COLUMN IF NOT EXISTS last_recalc JSON"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция warehouse last_recalc: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE product_document ADD COLUMN IF NOT EXISTS driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция product_document.driver_id: {e}")

        try:
            db.session.execute(db.text(
                "ALTER TABLE drivers ADD COLUMN IF NOT EXISTS image_url VARCHAR(500)"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция drivers.image_url: {e}")

        # warehouse.vat_enabled — работает ли склад с НДС. По умолчанию TRUE
        # для всех существующих складов (сохраняем текущее поведение).
        # Менеджер потом сам снимет галочку у складов где НДС не нужен.
        try:
            db.session.execute(db.text(
                "ALTER TABLE warehouse ADD COLUMN IF NOT EXISTS "
                "vat_enabled BOOLEAN NOT NULL DEFAULT TRUE"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция warehouse.vat_enabled: {e}")

        # kp_history.signed_at — отметка о подписанном контракте. Если
        # задана — КП заморожено, не пересчитывается от изменений в магазине.
        try:
            db.session.execute(db.text(
                "ALTER TABLE kp_history ADD COLUMN IF NOT EXISTS signed_at TIMESTAMP"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция kp_history.signed_at: {e}")

        # warehouse_formula.cost_formula — формула «Себестоимость без маржи».
        # Опциональна, считается за один проход с основной формулой и доставкой.
        # product_warehouse_cost.calculated_cost_no_margin — её результат на товар.
        # Оба NULL по умолчанию — заполняются только после ручного пересчёта склада.
        try:
            db.session.execute(db.text(
                "ALTER TABLE warehouse_formula ADD COLUMN IF NOT EXISTS cost_formula TEXT"
            ))
            db.session.execute(db.text(
                "ALTER TABLE product_warehouse_cost "
                "ADD COLUMN IF NOT EXISTS calculated_cost_no_margin FLOAT"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция cost_formula / calculated_cost_no_margin: {e}")

        # kp_share / kp_super_admin_access — таблицы для функции «Поделиться КП».
        # db.create_all() выше уже их создаёт, но индекс UNIQUE может не проставиться
        # на старой инсталляции если раньше таблица создавалась вручную. Защитный
        # ALTER гарантирует что unique constraint на месте.
        try:
            db.session.execute(db.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_kp_share_target
                ON kp_share (kp_history_id, shared_with_user_id)
            """))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция kp_share index: {e}")

        # kp_history.client_id — привязка к адресной книге (kp_client).
        # На старых инсталляциях колонки не было, db.create_all не добавляет
        # колонки в существующие таблицы — нужен явный ALTER.
        try:
            db.session.execute(db.text(
                "ALTER TABLE kp_history ADD COLUMN IF NOT EXISTS "
                "client_id INTEGER REFERENCES kp_client(id)"
            ))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_kp_history_client_id "
                "ON kp_history(client_id)"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция kp_history.client_id: {e}")

        # system_users.is_owner — заменяет хардкод по email во всех проверках
        # «главного админа». Бутстрап один раз: ставим TRUE для пользователя
        # с email из ENV OWNER_EMAIL (по умолчанию bocan.anton@mail.ru), но
        # только если в системе ещё нет ни одного owner'а — это защита от
        # случайного снятия флага в БД и повторного бутстрапа в чужой email.
        try:
            db.session.execute(db.text(
                "ALTER TABLE system_users ADD COLUMN IF NOT EXISTS "
                "is_owner BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            db.session.commit()
            existing = db.session.execute(
                db.text("SELECT COUNT(*) FROM system_users WHERE is_owner = TRUE")
            ).scalar() or 0
            if existing == 0:
                bootstrap_email = (os.environ.get('OWNER_EMAIL') or 'bocan.anton@mail.ru').lower()
                db.session.execute(
                    db.text("UPDATE system_users SET is_owner = TRUE "
                            "WHERE LOWER(email) = :em"),
                    {'em': bootstrap_email}
                )
                db.session.commit()
                print(f"ℹ️ is_owner bootstrap: {bootstrap_email}")
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция system_users.is_owner: {e}")

        # product_warehouse_cost.quantity — остаток на складе для товара.
        # Бэкфилл: для строк где quantity ещё 0, копируем product.quantity,
        # если supplier товара совпадает с supplier склада (т.е. это «основной»
        # склад товара — для BIO это warehouse_id=2). Без этого после миграции
        # все товары станут «нет в наличии», т.к. _apply_min_price теперь
        # учитывает quantity > 0.
        try:
            db.session.execute(db.text(
                "ALTER TABLE product_warehouse_cost "
                "ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 0"
            ))
            db.session.commit()
            db.session.execute(db.text("""
                UPDATE product_warehouse_cost AS pwc
                SET quantity = p.quantity
                FROM product p, warehouse w
                WHERE pwc.product_id = p.id
                  AND pwc.warehouse_id = w.id
                  AND p.supplier_id = w.supplier_id
                  AND pwc.quantity = 0
                  AND COALESCE(p.quantity, 0) > 0
            """))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция product_warehouse_cost.quantity: {e}")

        # category.slug должен быть уникальным во всём магазине: маршрут
        # /category/{slug} однозначно резолвится только при уникальности.
        # Раньше unique=False допускал дубли (родитель и подкатегория с одним
        # slug), и провалиться в подкатегорию было нельзя — открывался родитель.
        # Сначала переименовываем существующие дубли (slug, slug-2, slug-3, ...),
        # потом ставим UNIQUE-индекс. IF NOT EXISTS — идемпотентно.
        try:
            dup_rows = db.session.execute(db.text("""
                SELECT slug FROM category GROUP BY slug HAVING COUNT(*) > 1
            """)).fetchall()
            for (dup_slug,) in dup_rows:
                rows = db.session.execute(
                    db.text("SELECT id FROM category WHERE slug = :s ORDER BY id"),
                    {"s": dup_slug},
                ).fetchall()
                # Первая запись остаётся как есть; остальным даём суффикс -2, -3...
                for n, (cat_id,) in enumerate(rows[1:], start=2):
                    new_slug = f"{dup_slug}-{n}"
                    # на всякий случай страхуемся от коллизии и с уже занятыми
                    while db.session.execute(
                        db.text("SELECT 1 FROM category WHERE slug = :s LIMIT 1"),
                        {"s": new_slug},
                    ).first():
                        n += 1
                        new_slug = f"{dup_slug}-{n}"
                    db.session.execute(
                        db.text("UPDATE category SET slug = :ns WHERE id = :id"),
                        {"ns": new_slug, "id": cat_id},
                    )
                    print(f"  category.slug дубль исправлен: id={cat_id} '{dup_slug}' -> '{new_slug}'")
            db.session.commit()
            db.session.execute(db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_category_slug ON category(slug)"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция category.slug UNIQUE: {e}")

        # Bulk-индексы под FK и горячие фильтры. CREATE INDEX IF NOT EXISTS —
        # идемпотентно, можно гонять при каждом старте. Создание индекса на
        # большой таблице блокирует её на запись на время — в продакшне это
        # секунды-десятки секунд, для нашего размера БД безопасно. Если станет
        # критично — переехать на CREATE INDEX CONCURRENTLY (но он требует
        # autocommit, нужен будет отдельный коннект вне транзакции).
        index_migrations = [
            # product
            ("idx_product_supplier_id", "product(supplier_id)"),
            ("idx_product_status_id", "product(status)"),
            # product_warehouse_cost
            ("idx_pwc_warehouse_id", "product_warehouse_cost(warehouse_id)"),
            # product_characteristic / product_document
            ("idx_product_characteristic_product_id", "product_characteristic(product_id)"),
            ("idx_product_document_product_id", "product_document(product_id)"),
            ("idx_product_document_driver_id", "product_document(driver_id)"),
            # cart
            ("idx_cart_user_id", "cart(user_id)"),
            ("idx_cart_product_id", "cart(product_id)"),
            # orders
            ("idx_orders_user_id", "orders(user_id)"),
            ("idx_orders_status_id", "orders(status_id)"),
            ("idx_order_items_order_id", "order_items(order_id)"),
            ("idx_order_items_product_id", "order_items(product_id)"),
            ("idx_order_managers_order_id", "order_managers(order_id)"),
            ("idx_order_managers_manager_id", "order_managers(manager_id)"),
            ("idx_order_managers_assigned_by", "order_managers(assigned_by)"),
            # favorites
            ("idx_favorites_user_id", "favorites(user_id)"),
            ("idx_favorites_product_id", "favorites(product_id)"),
            # kp_history / kp_share
            ("idx_kp_history_user_id", "kp_history(user_id)"),
            ("idx_kp_history_created_at", "kp_history(created_at DESC)"),
            ("idx_kp_share_created_by", "kp_share(created_by)"),
            # warehouse
            ("idx_warehouse_supplier_id", "warehouse(supplier_id)"),
            ("idx_warehouse_variable_warehouse_id", "warehouse_variable(warehouse_id)"),
            # ai_import_logs
            ("idx_ai_import_logs_product_id", "ai_import_logs(product_id)"),
        ]
        for idx_name, idx_def in index_migrations:
            try:
                db.session.execute(db.text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}"
                ))
                db.session.commit()
            except Exception as e:
                # Если таблица/колонка ещё не существует (старая инсталляция
                # без какой-то миграции) — пропускаем, не валим весь старт.
                db.session.rollback()
                print(f"⚠️ Индекс {idx_name}: {e}")

        # pg_trgm + GIN-индекс по product.name — ускоряет ILIKE '%query%'
        # в десятки раз. Используется и в /products/search, и в фильтре
        # «Поиск» на админ-странице товаров. B-tree индекс тут бесполезен —
        # ведущий % заставляет Postgres делать Seq Scan на всей таблице.
        # Расширение можно установить только под superuser; на Render-managed
        # Postgres у нас права есть. На случай если нет — try/except.
        try:
            db.session.execute(db.text(
                "CREATE EXTENSION IF NOT EXISTS pg_trgm"
            ))
            db.session.commit()
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS idx_product_name_trgm "
                "ON product USING gin (name gin_trgm_ops)"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Миграция pg_trgm + idx_product_name_trgm: {e}")

        # Создаем системного пользователя по умолчанию
        create_default_system_user()

    return app


def create_default_system_user():
    """Создание системного пользователя по умолчанию"""
    try:
        # Проверяем, существует ли уже пользователь с таким email
        existing_user = SystemUser.query.filter_by(email='bocan.anton@mail.ru').first()
        
        if not existing_user:
            # Создаем нового системного пользователя
            admin_user = SystemUser(
                full_name='Администратор',
                email='bocan.anton@mail.ru',
                phone='+7 (777) 777-77-77',
                # Устанавливаем все права доступа
                access_orders=True,
                access_catalog=True,
                access_clients=True,
                access_users=True,
                access_settings=True,
                access_dashboard=True,
                access_brands=True,
                access_statuses=True,
                access_pages=True
            )
            
            # Устанавливаем пароль
            admin_user.set_password('1')
            
            # Сохраняем в базу данных
            db.session.add(admin_user)
            db.session.commit()
            
            print("✅ Системный пользователь создан: bocan.anton@mail.ru")
        else:
            print("ℹ️ Системный пользователь уже существует: bocan.anton@mail.ru")
            
    except Exception as e:
        print(f"❌ Ошибка при создании системного пользователя: {e}")
        db.session.rollback()


app = create_app()


@app.route('/')
def index():
    return {"message": "POSPRO API Server is running", "status": "ok"}


@app.route('/api')
def api_index():
    return {"message": "POSPRO API", "version": "1.0", "status": "ok"}


@app.route('/uploads/products/<int:product_id>/<filename>')
def serve_product_file(product_id, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER'], 'products', str(product_id))
    full_path = os.path.join(folder, filename)
    
    # Отладочная информация
    print(f"File request: {filename}")
    print(f"Product folder: {folder}")
    print(f"Full path: {full_path}")
    print(f"File exists: {os.path.exists(full_path)}")
    print(f"UPLOAD_FOLDER: {app.config['UPLOAD_FOLDER']}")
    
    if not os.path.exists(full_path):
        print(f"File not found: {full_path}")
        return "File not found", 404
    
    return send_from_directory(folder, filename)


@app.route('/uploads/products/<int:product_id>/documents/<filename>')
def serve_product_document(product_id, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER'], 'products', str(product_id), 'documents')
    full_path = os.path.join(folder, filename)
    
    print(f"Document request: {filename}")
    print(f"Documents folder: {folder}")
    print(f"Full path: {full_path}")
    print(f"File exists: {os.path.exists(full_path)}")
    
    if not os.path.exists(full_path):
        print(f"Document not found: {full_path}")
        return "Document not found", 404
    
    return send_file(full_path, as_attachment=True, download_name=filename)


@app.route('/uploads/products/<int:product_id>/drivers/<filename>')
def serve_product_driver(product_id, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER'], 'products', str(product_id), 'drivers')
    full_path = os.path.join(folder, filename)
    
    print(f"Driver request: {filename}")
    print(f"Drivers folder: {folder}")
    print(f"Full path: {full_path}")
    print(f"File exists: {os.path.exists(full_path)}")
    
    if not os.path.exists(full_path):
        print(f"Driver not found: {full_path}")
        return "Driver not found", 404
    
    return send_file(full_path, as_attachment=True, download_name=filename)


@app.route('/uploads/brands/<int:brand_id>/<filename>')
def serve_brand_image(brand_id, filename):
    return send_from_directory(
        os.path.join(app.config['UPLOAD_FOLDER'], 'brands', str(brand_id)),
        filename
    )


@app.route('/uploads/categories/<int:category_id>/<filename>')
def serve_category_image(category_id, filename):
    return send_from_directory(
        os.path.join(app.config['UPLOAD_FOLDER'], 'categories', str(category_id)),
        filename
    )


@app.route('/uploads/help/<int:article_id>/<filename>')
def serve_help_video(article_id, filename):
    return send_from_directory(
        os.path.join(app.config['UPLOAD_FOLDER'], 'help', str(article_id)),
        filename
    )


@app.route('/uploads/drivers/<int:driver_id>/image/<filename>')
def serve_driver_image(driver_id, filename):
    return send_from_directory(
        os.path.join(app.config['UPLOAD_FOLDER'], 'drivers', str(driver_id), 'image'),
        filename,
    )


@app.route('/uploads/drivers/<int:driver_id>/<filename>')
def serve_driver_file(driver_id, filename):
    return send_file(
        os.path.join(app.config['UPLOAD_FOLDER'], 'drivers', str(driver_id), filename),
        as_attachment=True,
        download_name=filename,
    )


@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    upload_dir = app.config['UPLOAD_FOLDER']
    return send_from_directory(upload_dir, filename)


@app.route('/uploads/banners/<int:banner_id>/<filename>')
def serve_banner_image(banner_id, filename):
    """Обслуживание изображений баннеров"""
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'banners', str(banner_id))
    return send_from_directory(upload_dir, filename)


@app.route('/uploads/banners/small_banners/<int:banner_id>/<filename>')
def serve_small_banner_image(banner_id, filename):
    """Обслуживание изображений малых баннеров"""
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'banners', 'small_banners', str(banner_id))
    return send_from_directory(upload_dir, filename)


@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    """Универсальный маршрут для обслуживания загруженных файлов"""
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Отладочная информация
    print(f"File request: {filename}")
    print(f"Full path: {file_path}")
    print(f"File exists: {os.path.exists(file_path)}")
    print(f"UPLOAD_FOLDER: {app.config['UPLOAD_FOLDER']}")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return "File not found", 404
    
    # Определяем директорию и имя файла
    directory = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    
    return send_from_directory(directory, file_name)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)
