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
from routes.dashboard import dashboard_bp
from routes.catalog_visibility import catalog_visibility_bp
from routes.order_statuses import order_statuses_bp
from routes.product_availability_statuses import product_availability_statuses_bp
from routes.public_product_availability_statuses import public_product_availability_statuses_bp
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

    # 🔹 Видимость каталогов (публичный + админский под /api)
    app.register_blueprint(catalog_visibility_bp, url_prefix='/api')  # /api/catalog-visibility, /api/admin-catalog-visibility
    
    # 🔹 Статусы заказов
    app.register_blueprint(order_statuses_bp, url_prefix='/api/admin')  # /api/admin/order-statuses
    
    # 🔹 Статусы наличия товара (админка)
    app.register_blueprint(product_availability_statuses_bp, url_prefix='/api/admin')  # /api/admin/product-availability-statuses
    
    # 🔹 Статусы наличия товара (публичные)
    app.register_blueprint(public_product_availability_statuses_bp, url_prefix='/api')  # /api/product-availability-statuses/check/*

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

    # Настройки загрузки файлов берутся из Config
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
    app.config['ALLOWED_EXTENSIONS'] = Config.ALLOWED_EXTENSIONS
    app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

    # Создаём папку для загрузок при первом запуске
    print(f"Creating uploads folder: {app.config['UPLOAD_FOLDER']}")
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    with app.app_context():
        db.create_all()
        
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
