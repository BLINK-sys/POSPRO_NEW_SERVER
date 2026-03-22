"""
BIO API data collector.
Fetches products from BIO API, converts prices, saves to intermediate SQLite DB.
Adapted from BioApiNewShop/bio_api.py.
"""

import logging
import os
import sqlite3
import requests

from . import rates_data

log = logging.getLogger(__name__)

BASE_URL = "http://api.bioshop.ru:8030"
AUTH_CREDENTIALS = {
    "login": "dilyara@pospro.kz",
    "password": "qo8qe7ti"
}

DB_PATH = os.environ.get("BIO_DB_PATH", os.path.join(os.path.dirname(__file__), "products.db"))


# ============================================================
# Delivery cost & volume calculations
# ============================================================

def calculate_delivery_cost(weight_kg, volume_m3):
    volumetric_weight = volume_m3 * 200
    delivery_weight = max(weight_kg, volumetric_weight)

    if delivery_weight <= 30:
        return 37700
    elif delivery_weight <= 300:
        excess = delivery_weight - 30
        return 9000 + (excess * 215) + 12000 + (excess * 27) + 11700 + 5000 + (excess * 19)
    elif delivery_weight <= 1000:
        excess_300 = delivery_weight - 300
        excess_1000 = max(0, delivery_weight - 1000)
        c1 = 9000 + (270 * 215) + (excess_300 * 164) + (excess_1000 * 143)
        c2 = 12000 + (270 * 27) + (excess_300 * 15) + excess_1000 + 11700
        c3 = 5000 + (270 * 19) + (excess_300 * 2) + (excess_1000 * 9) + 11700
        return c1 + c2 + c3
    else:
        excess_300 = 700
        excess_1000 = 0
        c1 = 9000 + (270 * 215) + (excess_300 * 164) + (excess_1000 * 143)
        c2 = 12000 + (270 * 27) + (excess_300 * 15) + excess_1000 + 11700
        c3 = 5000 + (270 * 19) + (excess_300 * 2) + (excess_1000 * 9) + 11700
        return c1 + c2 + c3


def calculate_volume_from_dimensions(size_gross):
    if not size_gross or size_gross == "0":
        return 0
    try:
        dimensions = size_gross.lower().replace("\u0445", "x").split("x")
        if len(dimensions) != 3:
            return 0
        w, h, d = map(lambda x: float(x) / 1000, dimensions)
        return w * h * d
    except (ValueError, IndexError):
        return 0


# ============================================================
# Image URL normalization
# ============================================================

def normalize_image_url(img_url):
    if not img_url or img_url == "":
        return None
    if img_url.startswith("http://") or img_url.startswith("https://"):
        return img_url
    if img_url.startswith("/"):
        return f"https://portal.holdingbio.ru{img_url}"
    return f"https://portal.holdingbio.ru/{img_url}"


# ============================================================
# Database operations
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id TEXT,
        api_id TEXT UNIQUE,
        img TEXT,
        FOREIGN KEY (parent_id) REFERENCES categories(id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_categories_parent_id ON categories(parent_id)")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS brands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL UNIQUE,
        country TEXT
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_brands_brand ON brands(brand)")

    # Drop and recreate products table to ensure clean schema
    cursor.execute("DROP TABLE IF EXISTS product_properties")
    cursor.execute("DROP TABLE IF EXISTS products")

    cursor.execute("""
    CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id TEXT,
        brand_id INTEGER,
        fullName TEXT,
        inStock INTEGER,
        name TEXT,
        price REAL,
        priceCurrency TEXT,
        img TEXT,
        description TEXT,
        FOREIGN KEY (category_id) REFERENCES categories(id),
        FOREIGN KEY (brand_id) REFERENCES brands(id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand_id ON products(brand_id)")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        property_name TEXT NOT NULL,
        property_value TEXT,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_product_properties_product_id ON product_properties(product_id)")

    # Clear categories and brands for fresh import
    cursor.execute("DELETE FROM categories")
    cursor.execute("DELETE FROM brands")

    conn.commit()
    conn.close()
    log.info("Database initialized")


def save_category_to_db(category_data, parent_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    category_api_id = category_data.get("id")
    category_name = category_data.get("name", "Unknown Category")

    if not category_api_id:
        conn.close()
        return None

    category_id = category_api_id

    cursor.execute("SELECT id FROM categories WHERE api_id = ?", (category_api_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("UPDATE categories SET name = ?, parent_id = ? WHERE api_id = ?",
                        (category_name, parent_id, category_api_id))
    else:
        cursor.execute("INSERT INTO categories (id, name, parent_id, api_id) VALUES (?, ?, ?, ?)",
                        (category_id, category_name, parent_id, category_api_id))

    conn.commit()
    conn.close()
    return category_id


def get_or_create_brand(brand_name, country=None):
    if not brand_name:
        return None

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM brands WHERE brand = ?", (brand_name,))
    existing = cursor.fetchone()

    if existing:
        brand_id = existing[0]
        conn.close()
        return brand_id

    if not country or country == "":
        conn.close()
        return None

    try:
        cursor.execute("INSERT INTO brands (brand, country) VALUES (?, ?)", (brand_name, country))
        brand_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        cursor.execute("SELECT id FROM brands WHERE brand = ?", (brand_name,))
        existing = cursor.fetchone()
        brand_id = existing[0] if existing else None

    conn.close()
    return brand_id


def import_categories(categories_response):
    if "error" in categories_response:
        return False

    categories_map = {}

    for category_group in categories_response:
        main_id = category_group.get("id")
        main_name = category_group.get("name", "Unknown Category")

        if main_id:
            saved_main_id = save_category_to_db({"id": main_id, "name": main_name}, parent_id=None)
            categories_map[main_id] = saved_main_id

        for sub in category_group.get("categories", []):
            sub_id = sub.get("id")
            if sub_id and main_id:
                saved_sub_id = save_category_to_db({"id": sub_id, "name": sub.get("name", "")}, parent_id=saved_main_id)
                categories_map[sub_id] = saved_sub_id

    log.info(f"Imported {len(categories_map)} categories")
    return categories_map


def update_category_image(category_id, product_img_url=None):
    if not category_id:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT img FROM categories WHERE id = ?", (category_id,))
    existing = cursor.fetchone()
    if existing and existing[0]:
        conn.close()
        return

    if product_img_url:
        img = product_img_url if product_img_url.startswith("http") else normalize_image_url(product_img_url)
        cursor.execute("UPDATE categories SET img = ? WHERE id = ?", (img, category_id))
        conn.commit()
        conn.close()
        return

    cursor.execute("""
        SELECT img FROM products WHERE category_id = ? AND img IS NOT NULL AND img != ''
        ORDER BY id ASC LIMIT 1
    """, (category_id,))
    row = cursor.fetchone()
    if row and row[0]:
        img = row[0] if row[0].startswith("http") else normalize_image_url(row[0])
        cursor.execute("UPDATE categories SET img = ? WHERE id = ?", (img, category_id))
        conn.commit()

    conn.close()


def update_all_category_images():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, parent_id FROM categories")
    all_cats = cursor.fetchall()

    # Child categories first
    for cat_id, cat_name, parent_id in all_cats:
        if parent_id is None:
            continue
        cursor.execute("SELECT img FROM categories WHERE id = ?", (cat_id,))
        ex = cursor.fetchone()
        if ex and ex[0]:
            continue
        cursor.execute("""
            SELECT img FROM products WHERE category_id = ? AND img IS NOT NULL AND img != ''
            ORDER BY id ASC LIMIT 1
        """, (cat_id,))
        row = cursor.fetchone()
        if row and row[0]:
            img = row[0] if row[0].startswith("http") else normalize_image_url(row[0])
            cursor.execute("UPDATE categories SET img = ? WHERE id = ?", (img, cat_id))

    # Main categories
    for cat_id, cat_name, parent_id in all_cats:
        if parent_id is not None:
            continue
        cursor.execute("SELECT img FROM categories WHERE id = ?", (cat_id,))
        ex = cursor.fetchone()
        if ex and ex[0]:
            continue
        cursor.execute("""
            SELECT img FROM categories WHERE parent_id = ? AND img IS NOT NULL AND img != ''
            ORDER BY id ASC LIMIT 1
        """, (cat_id,))
        row = cursor.fetchone()
        if row and row[0]:
            img = row[0] if row[0].startswith("http") else normalize_image_url(row[0])
            cursor.execute("UPDATE categories SET img = ? WHERE id = ?", (img, cat_id))
        else:
            cursor.execute("""
                SELECT img FROM products WHERE category_id = ? AND img IS NOT NULL AND img != ''
                ORDER BY id ASC LIMIT 1
            """, (cat_id,))
            row2 = cursor.fetchone()
            if row2 and row2[0]:
                img = row2[0] if row2[0].startswith("http") else normalize_image_url(row2[0])
                cursor.execute("UPDATE categories SET img = ? WHERE id = ?", (img, cat_id))

    conn.commit()
    conn.close()
    log.info("Category images updated")


def save_product_to_db(product, category_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    exchange_rates = rates_data.exchange_rates
    bio_rates_dict = rates_data.bio_rates

    # Currency (prefer dilerCurrency since we use dilerPrice)
    price_currency = (
        product.get("dilerCurrency") or product.get("priceCurrency") or "RUB"
    ).replace("\u0423\u0415 ", "").replace(" \u0412\u041d", "").replace(" 1.5", "")
    original_price = product.get("dilerPrice", 0)

    weight_gross = product.get("weightGross", 0)
    size_gross = product.get("sizeGross", "0\u04450\u04450")

    has_price = original_price and original_price > 0
    has_weight = weight_gross and weight_gross > 0
    has_dimensions = size_gross and size_gross != "0\u04450\u04450" and size_gross != "0"

    if not has_price or not has_weight or not has_dimensions:
        price = 0
        price_currency = "KZT"
    else:
        volume = calculate_volume_from_dimensions(size_gross)
        delivery_cost = calculate_delivery_cost(weight_gross, volume)

        if price_currency in ['EUR', 'USD']:
            price_in_rubles = original_price * bio_rates_dict.get(price_currency, 1)
            price_in_tenge = price_in_rubles * exchange_rates.get('RUB', 1)
        else:
            price_in_tenge = original_price * exchange_rates.get(price_currency, 1)

        converted_price = price_in_tenge / 1.22 * 1.16
        converted_price = converted_price + delivery_cost
        converted_price = converted_price * 1.16

        price = int(round(converted_price))
        price_currency = "KZT"

    brand_name = product.get("brand")
    country = product.get("country")
    brand_id = get_or_create_brand(brand_name, country) if brand_name else None
    img_url = normalize_image_url(product.get("img"))

    product_name = product.get("name", "")
    product_fullname = product.get("fullName", "")

    cursor.execute("""
        SELECT id FROM products WHERE name = ? AND fullName = ? AND category_id = ?
    """, (product_name, product_fullname, category_id))
    existing_product = cursor.fetchone()

    if existing_product is None:
        cursor.execute("""
        INSERT INTO products (category_id, brand_id, fullName, inStock, name, price, priceCurrency, img, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (category_id, brand_id, product_fullname, product.get("inStock"),
              product_name, price, price_currency, img_url, product.get("description", "")))
        product_id = cursor.lastrowid
    else:
        product_id = existing_product[0]
        cursor.execute("""
        UPDATE products SET category_id=?, brand_id=?, fullName=?, inStock=?, name=?, price=?, priceCurrency=?, img=?, description=?
        WHERE id = ?
        """, (category_id, brand_id, product_fullname, product.get("inStock"),
              product_name, price, price_currency, img_url, product.get("description", ""), product_id))

    conn.commit()
    conn.close()

    if img_url and category_id:
        update_category_image(category_id, product_img_url=img_url)
        c2 = sqlite3.connect(DB_PATH)
        cur2 = c2.cursor()
        cur2.execute("SELECT parent_id FROM categories WHERE id = ?", (category_id,))
        parent = cur2.fetchone()
        c2.close()
        if parent and parent[0]:
            update_category_image(parent[0], product_img_url=img_url)

    return product_id


def save_product_properties(product_id, product_details):
    if not product_details or not isinstance(product_details, dict) or not product_id:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM product_properties WHERE product_id = ?", (product_id,))

    for field, label in [("sizeNet", "Размер без упаковки"), ("sizeGross", "Размер в упаковке")]:
        val = product_details.get(field)
        if val and val != "" and val != "0" and val != "0х0х0":
            cursor.execute("INSERT INTO product_properties (product_id, property_name, property_value) VALUES (?,?,?)",
                           (product_id, label, str(val)))

    model = product_details.get("model")
    if model and model != "":
        cursor.execute("INSERT INTO product_properties (product_id, property_name, property_value) VALUES (?,?,?)",
                       (product_id, "Модель", str(model)))

    code = product_details.get("code")
    if code and code != "":
        cursor.execute("INSERT INTO product_properties (product_id, property_name, property_value) VALUES (?,?,?)",
                       (product_id, "code", str(code)))

    for prop_item in product_details.get("secondaryProps", []):
        if isinstance(prop_item, dict):
            pn = prop_item.get("prop", "")
            pv = prop_item.get("value", "")
            if pn and pv is not None and pv != "":
                cursor.execute("INSERT INTO product_properties (product_id, property_name, property_value) VALUES (?,?,?)",
                               (product_id, pn, str(pv)))

    conn.commit()
    conn.close()


# ============================================================
# BIO API fetch functions
# ============================================================

def fetch_categories():
    try:
        response = requests.post(f"{BASE_URL}/categories", json=AUTH_CREDENTIALS, timeout=180)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"Error fetching categories: {e}")
        return {"error": str(e)}


def fetch_products_by_category(category_id):
    try:
        payload = {**AUTH_CREDENTIALS, "categoryId": category_id}
        response = requests.post(f"{BASE_URL}/products", json=payload, timeout=180)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"Error fetching products for category {category_id}: {e}")
        return {"error": str(e)}


def fetch_product_details(product_code):
    try:
        payload = {**AUTH_CREDENTIALS, "code": product_code}
        response = requests.post(f"{BASE_URL}/product", json=payload, timeout=180)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"Error fetching details for {product_code}: {e}")
        return {}


# ============================================================
# Main collection function
# ============================================================

def run_collection(progress):
    """
    Main entry point: fetch all products from BIO API and save to SQLite.
    Updates progress object for real-time UI feedback.
    """
    log.info("Starting BIO data collection")
    init_db()

    # Fetch categories
    categories_response = fetch_categories()
    if isinstance(categories_response, dict) and "error" in categories_response:
        raise Exception(f"Failed to fetch categories: {categories_response['error']}")

    categories_map = import_categories(categories_response)
    if not categories_map:
        raise Exception("Failed to import categories")

    # Count total subcategories for progress
    total_subcategories = 0
    for group in categories_response:
        total_subcategories += len(group.get("categories", []))

    progress.update(collecting_total_categories=total_subcategories)

    total_products = 0
    processed_categories = 0

    for category_group in categories_response:
        for sub_category in category_group.get("categories", []):
            category_api_id = sub_category.get("id")
            cat_name = sub_category.get("name", "Unknown")

            if not category_api_id or category_api_id not in categories_map:
                processed_categories += 1
                progress.update(
                    collecting_processed_categories=processed_categories,
                    collecting_current_category=cat_name
                )
                continue

            category_db_id = categories_map[category_api_id]
            progress.update(collecting_current_category=cat_name)

            products = fetch_products_by_category(category_api_id)

            if isinstance(products, list):
                for product in products:
                    product_details = fetch_product_details(product.get("code"))
                    if isinstance(product_details, dict):
                        product.update(product_details)

                    product_id = save_product_to_db(product, category_id=category_db_id)

                    if product_id and product_details:
                        save_product_properties(product_id, product_details)

                    total_products += 1
                    progress.increment_products_count()

            processed_categories += 1
            progress.update(collecting_processed_categories=processed_categories)
            log.info(f"Category '{cat_name}': done. Total products so far: {total_products}")

    # Update category images
    update_all_category_images()

    log.info(f"BIO collection complete. Total products: {total_products}")
    return total_products


if __name__ == "__main__":
    # Standalone execution for debugging
    from progress import ImportProgress
    p = ImportProgress()
    p.update(status="running", stage="collecting")
    from . import currency
    currency.update_all_rates(rates_data)
    run_collection(p)
    print(f"Collected {p.collecting_products_count} products")
