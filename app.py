from flask import Flask, send_from_directory
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
from routes.profile import profile_bp
from routes.public_homepage import public_homepage_bp
from routes.small_banners import small_banner_bp
from routes.system_brands import system_brands_bp
from routes.system_users import system_users_bp
from routes.upload import upload_bp
from routes.brands_statuses import bp as brands_statuses_bp
import os
from routes.upload_admin import upload_admin_bp
from routes.favorites import favorites_bp
from routes.cart import cart_bp
from routes.orders import orders_bp
from routes.order_statuses import order_statuses_bp
from routes.product_availability_statuses import product_availability_statuses_bp
from routes.public_product_availability_statuses import public_product_availability_statuses_bp


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

    # 🔹 Загрузка файлов и медиа
    app.register_blueprint(upload_bp, url_prefix='/upload')  # /upload/*

    # 🔹 Метаданные (статусы, бренды и пр.)
    app.register_blueprint(brands_statuses_bp, url_prefix='/meta')  # /meta/*

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

    # Настройка папки загрузок - используем конфигурацию из Config
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
    app.config['ALLOWED_EXTENSIONS'] = Config.ALLOWED_EXTENSIONS
    app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH

    # Создаём папку для загрузок при первом запуске
    print(f"📂 Создаём папку uploads: {app.config['UPLOAD_FOLDER']}")
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    return app


app = create_app()


@app.route('/')
def index():
    return {
        "message": "POSPRO Shop API Server",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "categories": "/categories",
            "products": "/products", 
            "auth": "/auth",
            "upload": "/upload",
            "api": "/api"
        }
    }


@app.route('/uploads/products/<int:product_id>/<filename>')
def serve_product_file(product_id, filename):
    folder = os.path.join(app.config['UPLOAD_FOLDER'], 'products', str(product_id))
    full_path = os.path.join(folder, filename)
    
    # Отладочная информация
    print(f"🔍 Запрос файла: {filename}")
    print(f"📁 Папка продукта: {folder}")
    print(f"📄 Полный путь: {full_path}")
    print(f"✅ Файл существует: {os.path.exists(full_path)}")
    print(f"📂 UPLOAD_FOLDER: {app.config['UPLOAD_FOLDER']}")
    
    if not os.path.exists(full_path):
        print(f"❌ Файл не найден: {full_path}")
        return "File not found", 404
    
    return send_from_directory(folder, filename)


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
    upload_dir = os.path.join(app.root_path, 'uploads')
    return send_from_directory(upload_dir, filename)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
