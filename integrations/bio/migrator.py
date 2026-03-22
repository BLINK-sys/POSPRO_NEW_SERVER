"""
Migrator: pushes data from intermediate SQLite DB to PosPro API.
Adapted from BioApiNewShop/migrate_from_products_db.py.
"""

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

# Settings
API_BASE_URL = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
DEFAULT_SUPPLIER_ID = 2

# State (reset per run)
JWT_TOKEN = None
brands_map = {}
categories_map = {}
brands_cache = {}
categories_cache = {}
characteristics_cache = {}
products_cache = {}
existing_brands_loaded = False
existing_categories_loaded = False
existing_characteristics_loaded = False
existing_products_loaded = False
products_cache_lock = threading.Lock()


def _reset_state():
    global JWT_TOKEN, brands_map, categories_map, brands_cache, categories_cache
    global characteristics_cache, products_cache
    global existing_brands_loaded, existing_categories_loaded, existing_characteristics_loaded, existing_products_loaded
    JWT_TOKEN = None
    brands_map = {}
    categories_map = {}
    brands_cache = {}
    categories_cache = {}
    characteristics_cache = {}
    products_cache = {}
    existing_brands_loaded = False
    existing_categories_loaded = False
    existing_characteristics_loaded = False
    existing_products_loaded = False


# ============================================================
# Helpers
# ============================================================

def get_auth_headers():
    headers = {'Content-Type': 'application/json'}
    if JWT_TOKEN:
        headers['Authorization'] = f'Bearer {JWT_TOKEN}'
    return headers


def normalize_url(api_url, endpoint):
    base_url = api_url.replace('/api', '') if '/api' in api_url else api_url
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def safe_slugify(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', str(text))
    russian_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    for ru, lat in russian_to_latin.items():
        text = text.replace(ru, lat)
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-').lower()


def sanitize_filename(filename):
    if not filename:
        return 'image.jpg'
    parsed = urlparse(filename)
    filename = os.path.basename(parsed.path) or 'image.jpg'
    if '?' in filename:
        filename = filename.split('?')[0]
    filename = filename.replace(' ', '_')
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    if not filename or '.' not in filename:
        timestamp = int(time.time() * 1000) % 1000000
        filename = f'image_{timestamp}.jpg'
    else:
        ext = filename.lower().split('.')[-1]
        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            base = filename.rsplit('.', 1)[0]
            base = re.sub(r'[<>:"/\\|?*]', '', base) or 'image'
            filename = f'{base}.jpg'
    return filename


def is_valid_image(content):
    if not content or len(content) < 4:
        return False
    sigs = [b'\xFF\xD8\xFF', b'\x89\x50\x4E\x47', b'GIF87a', b'GIF89a']
    for sig in sigs:
        if content.startswith(sig):
            return True
    if content.startswith(b'RIFF') and b'WEBP' in content[:12]:
        return True
    return False


def get_content_type(filename):
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    return {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp'}.get(ext, 'image/jpeg')


# ============================================================
# Auth
# ============================================================

def login(api_url, email='bocan.anton@mail.ru', password='1'):
    global JWT_TOKEN
    login_url = f"{api_url.replace('/api', '')}/auth/login" if '/api' in api_url else f"{api_url}/auth/login"
    try:
        resp = requests.post(login_url, json={'email': email, 'password': password},
                             headers={'Content-Type': 'application/json'}, timeout=60)
        if resp.status_code == 200:
            JWT_TOKEN = resp.json().get('token')
            log.info("Auth successful")
            return True
        log.error(f"Auth failed: {resp.status_code}")
        return False
    except Exception as e:
        log.error(f"Auth error: {e}")
        return False


# ============================================================
# Cache loaders
# ============================================================

def load_existing_characteristics(api_url):
    global existing_characteristics_loaded, characteristics_cache
    if existing_characteristics_loaded:
        return
    url = normalize_url(api_url, 'characteristics-list')
    try:
        resp = requests.get(url, headers=get_auth_headers(), timeout=60)
        if resp.status_code == 200:
            result = resp.json()
            if result.get('success') and result.get('data'):
                for ch in result['data']:
                    key = ch.get('characteristic_key', '')
                    if key:
                        characteristics_cache[key] = ch['id']
                existing_characteristics_loaded = True
                log.info(f"Loaded {len(characteristics_cache)} characteristics")
    except Exception as e:
        log.warning(f"Failed to load characteristics: {e}")


def load_existing_brands(api_url):
    global existing_brands_loaded, brands_cache
    if existing_brands_loaded:
        return
    url = normalize_url(api_url, 'meta/brands')
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200:
            for brand in resp.json():
                brands_cache[(brand.get('name', ''), brand.get('country', ''))] = brand['id']
            existing_brands_loaded = True
            log.info(f"Loaded {len(brands_cache)} brands")
    except Exception as e:
        log.warning(f"Failed to load brands: {e}")


def load_existing_categories(api_url):
    global existing_categories_loaded, categories_cache
    if existing_categories_loaded:
        return
    url = normalize_url(api_url, 'categories/')
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200:
            for cat in resp.json():
                categories_cache[(cat.get('name', ''), cat.get('parent_id'))] = cat['id']
            existing_categories_loaded = True
            log.info(f"Loaded {len(categories_cache)} categories")
    except Exception as e:
        log.warning(f"Failed to load categories: {e}")


def load_existing_products(api_url):
    global existing_products_loaded, products_cache
    if existing_products_loaded:
        return
    with products_cache_lock:
        if existing_products_loaded:
            return
        existing_products_loaded = True
        products_cache = {}

    url = normalize_url(api_url, 'products/')
    page = 1
    per_page = 200
    total_loaded = 0

    try:
        while True:
            resp = requests.get(url, params={'per_page': per_page, 'page': page},
                                headers=get_auth_headers(), timeout=120)
            if resp.status_code != 200:
                break

            data = resp.json()
            if isinstance(data, list):
                products = data
                has_more = len(products) == per_page
            elif isinstance(data, dict) and 'products' in data:
                products = data.get('products', [])
                has_more = page < data.get('total_pages', 1)
            else:
                break

            with products_cache_lock:
                for p in products:
                    sid = p.get('supplier_id')
                    if sid is not None and sid == DEFAULT_SUPPLIER_ID:
                        name = p.get('name', '').strip()
                        if name:
                            products_cache[name] = {'id': p['id'], 'supplier_id': sid}

            total_loaded += len(products)
            if not has_more or len(products) < per_page:
                break
            page += 1
            time.sleep(0.2)

        log.info(f"Loaded {total_loaded} products, {len(products_cache)} with supplier_id={DEFAULT_SUPPLIER_ID}")
    except Exception as e:
        log.warning(f"Failed to load products: {e}")


# ============================================================
# Create entities
# ============================================================

def create_characteristic(key, api_url):
    load_existing_characteristics(api_url)
    if key in characteristics_cache:
        return characteristics_cache[key]
    url = normalize_url(api_url, 'characteristics-list')
    try:
        resp = requests.post(url, json={'characteristic_key': key.strip()},
                             headers=get_auth_headers(), timeout=60)
        if resp.status_code == 201:
            result = resp.json()
            if result.get('success') and result.get('data'):
                cid = result['data'].get('id')
                characteristics_cache[key] = cid
                return cid
        elif resp.status_code == 400:
            load_existing_characteristics(api_url)
            return characteristics_cache.get(key)
    except Exception as e:
        log.warning(f"Create characteristic error: {e}")
    return None


def create_brand(name, country='', api_url=None):
    load_existing_brands(api_url)
    ck = (name, country)
    if ck in brands_cache:
        return brands_cache[ck]
    url = normalize_url(api_url, 'meta/brands')
    try:
        resp = requests.post(url, json={'name': name, 'country': country or '', 'description': '', 'image_url': None},
                             headers={'Content-Type': 'application/json'}, timeout=60)
        if resp.status_code == 200:
            bid = resp.json().get('id')
            brands_cache[ck] = bid
            return bid
    except Exception as e:
        log.warning(f"Create brand error: {e}")
    return None


def create_category(name, parent_id=None, image_url=None, api_url=None):
    load_existing_categories(api_url)
    ck = (name, parent_id)
    if ck in categories_cache:
        eid = categories_cache[ck]
        if image_url:
            upload_category_image_from_url(eid, image_url, api_url)
        return eid

    slug = safe_slugify(name) or f"category-{int(time.time())}"
    url = normalize_url(api_url, 'categories/with-image')
    try:
        resp = requests.post(url, data={'name': name, 'slug': slug, 'description': '',
                                        'parent_id': str(parent_id) if parent_id else ''}, timeout=60)
        if resp.status_code == 201:
            cid = resp.json().get('id')
            categories_cache[ck] = cid
            if image_url:
                upload_category_image_from_url(cid, image_url, api_url)
            return cid
    except Exception as e:
        log.warning(f"Create category error: {e}")
    return None


# ============================================================
# Images
# ============================================================

def upload_category_image_from_url(category_id, image_url, api_url):
    if not image_url or not category_id:
        return False
    cat_info = None
    try:
        resp = requests.get(normalize_url(api_url, f'categories/{category_id}'),
                            headers=get_auth_headers(), timeout=60)
        if resp.status_code == 200:
            cat_info = resp.json()
    except:
        pass
    if cat_info and cat_info.get('image_url', '').strip():
        return True
    image_url = str(image_url).strip()
    if image_url.startswith('/uploads/'):
        return True
    if not (image_url.startswith('http://') or image_url.startswith('https://')):
        return False
    try:
        img_resp = requests.get(image_url, timeout=30, stream=True)
        if img_resp.status_code != 200:
            return False
        filename = os.path.basename(urlparse(image_url).path) or 'image.jpg'
        upload_url = normalize_url(api_url, f'upload/category/{category_id}')
        files = {'file': (filename, img_resp.content, img_resp.headers.get('Content-Type', 'image/jpeg'))}
        resp = requests.post(upload_url, files=files,
                             headers={'Authorization': f'Bearer {JWT_TOKEN}'} if JWT_TOKEN else {}, timeout=60)
        return resp.status_code == 200
    except:
        return False


def download_image(image_url):
    try:
        resp = requests.get(image_url, timeout=30, stream=True)
        if resp.status_code != 200:
            return None, None
        content = resp.content
        if len(content) > 20 * 1024 * 1024 or not is_valid_image(content):
            return None, None
        cd = resp.headers.get('Content-Disposition', '')
        filename = cd.split('filename=')[1].strip('"\'') if 'filename=' in cd else sanitize_filename(image_url)
        return content, filename
    except:
        return None, None


def get_product_media(product_id, api_url):
    try:
        resp = requests.get(normalize_url(api_url, f'upload/media/{product_id}'),
                            headers=get_auth_headers(), timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else []
    except:
        pass
    return []


def get_product_characteristics(product_id, api_url):
    try:
        resp = requests.get(normalize_url(api_url, f'characteristics/{product_id}'),
                            headers=get_auth_headers(), timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return {ch.get('characteristic_id') for ch in data if ch.get('characteristic_id')}
    except:
        pass
    return set()


def add_product_image(product_id, image_url, api_url):
    if not image_url or not product_id:
        return False
    image_url = str(image_url).strip()
    if image_url.startswith('/uploads/products/'):
        return True
    if image_url.startswith('http://') or image_url.startswith('https://'):
        content, filename = download_image(image_url)
        if not content:
            return False
        try:
            upload_url = normalize_url(api_url, 'upload/upload_product')
            files = {'file': (filename, content, get_content_type(filename))}
            headers = {'Authorization': f'Bearer {JWT_TOKEN}'} if JWT_TOKEN else {}
            resp = requests.post(upload_url, files=files, data={'product_id': str(product_id)},
                                 headers=headers, timeout=120)
            return resp.status_code == 200
        except:
            return False
    return False


def add_product_characteristic(product_id, characteristic_id, value, api_url):
    if not product_id or not characteristic_id:
        return False
    try:
        resp = requests.post(normalize_url(api_url, f'characteristics/{product_id}'),
                             json={'characteristic_id': characteristic_id, 'value': str(value) if value else ''},
                             headers={'Content-Type': 'application/json',
                                      'Authorization': f'Bearer {JWT_TOKEN}'} if JWT_TOKEN else {'Content-Type': 'application/json'},
                             timeout=60)
        return resp.status_code == 201
    except:
        return False


# ============================================================
# Product creation/update
# ============================================================

def create_product(product_data, old_brand_id, old_category_id, api_url, progress=None):
    if not existing_products_loaded:
        load_existing_products(api_url)

    name = product_data.get('name') or product_data.get('fullName', '').strip()
    if not name:
        return None

    try:
        quantity = int(product_data.get('inStock', 0) or 0)
    except (ValueError, TypeError):
        quantity = 0

    description = product_data.get('description', '') or ''
    price = product_data.get('price', 0) or 0

    existing_id = None
    if name in products_cache:
        info = products_cache[name]
        if info.get('supplier_id') == DEFAULT_SUPPLIER_ID:
            existing_id = info['id']

    if existing_id:
        try:
            update_data = {
                'price': float(price) if price else 0,
                'quantity': quantity,
                'supplier_id': DEFAULT_SUPPLIER_ID,
                'is_visible': True
            }
            resp = requests.put(normalize_url(api_url, f'products/{existing_id}'),
                                json=update_data, headers=get_auth_headers(), timeout=60)
            if resp.status_code == 200:
                if progress:
                    progress.increment_migrating(updated=True)
                    # Check if product was previously hidden -> reactivated
                    progress.append_reactivated(name)
            else:
                if progress:
                    progress.append_migrating_error(f"Update failed for '{name}': {resp.status_code}")
                    progress.increment_migrating()
        except Exception as e:
            if progress:
                progress.append_migrating_error(f"Update error for '{name}': {e}")
                progress.increment_migrating()
        return existing_id

    # Create new product
    new_brand_id = brands_map.get(old_brand_id) if old_brand_id else None
    new_category_id = categories_map.get(old_category_id) if old_category_id else None

    name_hash = hashlib.md5(name.encode('utf-8')).hexdigest()[:8].upper()
    timestamp = int(time.time() * 1000) % 1000000
    article = f"MIGR-{name_hash}-{timestamp}"

    try:
        data = {
            'name': name, 'article': article,
            'price': float(price) if price else 0,
            'wholesale_price': 0, 'quantity': quantity,
            'status': None, 'is_visible': True, 'country': '',
            'brand_id': new_brand_id, 'description': description,
            'category_id': new_category_id, 'supplier_id': DEFAULT_SUPPLIER_ID
        }
        resp = requests.post(normalize_url(api_url, 'products/'),
                             json=data, headers=get_auth_headers(), timeout=60)
        if resp.status_code == 201:
            pid = resp.json().get('id')
            with products_cache_lock:
                products_cache[name] = {'id': pid, 'supplier_id': DEFAULT_SUPPLIER_ID}
            if progress:
                progress.increment_migrating(created=True)
            return pid
        else:
            if progress:
                progress.append_migrating_error(f"Create failed for '{name}': {resp.status_code}")
                progress.increment_migrating()
    except Exception as e:
        if progress:
            progress.append_migrating_error(f"Create error for '{name}': {e}")
            progress.increment_migrating()
    return None


# ============================================================
# Deactivation
# ============================================================

def deactivate_missing_products(local_product_names, api_url, progress=None):
    if not local_product_names:
        return

    if not existing_products_loaded:
        load_existing_products(api_url)

    products_to_deactivate = []
    with products_cache_lock:
        for server_name, product_info in products_cache.items():
            if product_info.get('supplier_id') == DEFAULT_SUPPLIER_ID:
                if server_name.strip().lower() not in local_product_names:
                    products_to_deactivate.append((product_info['id'], server_name))

    if not products_to_deactivate:
        log.info("No products to deactivate")
        return

    log.info(f"Deactivating {len(products_to_deactivate)} products")

    for pid, pname in products_to_deactivate:
        try:
            resp = requests.put(normalize_url(api_url, f'products/{pid}'),
                                json={'is_visible': False, 'quantity': 0},
                                headers=get_auth_headers(), timeout=60)
            if resp.status_code == 200:
                if progress:
                    progress.append_deactivated(pname)
            time.sleep(0.05)
        except Exception as e:
            log.warning(f"Deactivate error for '{pname}': {e}")


# ============================================================
# Main migration function
# ============================================================

def run_migration(progress, api_url=None, db_path=None):
    """
    Main entry point: migrates data from SQLite to PosPro API.
    Updates progress object for real-time UI feedback.
    """
    from .collector import DB_PATH as COLLECTOR_DB_PATH

    _reset_state()

    api_url = api_url or API_BASE_URL
    db_path = db_path or COLLECTOR_DB_PATH

    if not os.path.exists(db_path):
        raise Exception(f"Database not found: {db_path}")

    # Auth
    if not login(api_url):
        raise Exception("Authentication failed")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check structure
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    structure = {}
    for t in tables:
        cursor.execute(f"PRAGMA table_info({t})")
        structure[t] = [c[1] for c in cursor.fetchall()]

    # Find tables
    brands_table = next((t for t in structure if 'brand' in t.lower()), None)
    categories_table = next((t for t in structure if 'categor' in t.lower()), None)
    props_table = next((t for t in structure if 'product_propert' in t.lower() or 'property' in t.lower()), None)
    products_table = next((t for t in structure if 'product' in t.lower() and 'property' not in t.lower()), None)

    # Step 1: Characteristics
    log.info("Step 1: Creating characteristics...")
    if props_table and 'property_name' in structure[props_table]:
        cursor.execute(f"SELECT DISTINCT property_name FROM {props_table} WHERE property_name IS NOT NULL AND property_name != ''")
        for (pn,) in cursor.fetchall():
            if pn and pn.strip():
                create_characteristic(pn.strip(), api_url)
                time.sleep(0.2)

    # Step 2: Categories
    log.info("Step 2: Creating categories...")
    if categories_table:
        cols = structure[categories_table]
        cursor.execute(f"SELECT * FROM {categories_table} ORDER BY id")
        all_cats = cursor.fetchall()
        cats_dict = {}
        for row in all_cats:
            d = dict(zip(cols, row))
            cats_dict[d.get('id')] = d

        def create_cat_recursive(old_id, parent_new_id=None):
            if old_id not in cats_dict:
                return None
            cd = cats_dict[old_id]
            name = cd.get('name', '').strip()
            if not name:
                return None
            if old_id in categories_map:
                new_id = categories_map[old_id]
            else:
                img = cd.get('img') or cd.get('image') or cd.get('image_url')
                new_id = create_category(name, parent_new_id, img, api_url)
                if new_id:
                    categories_map[old_id] = new_id
                    time.sleep(0.2)
                else:
                    ck = (name, parent_new_id)
                    if ck in categories_cache:
                        new_id = categories_cache[ck]
                        categories_map[old_id] = new_id
            if new_id:
                for child_id, child_d in cats_dict.items():
                    if child_d.get('parent_id') == old_id:
                        create_cat_recursive(child_id, new_id)
            return new_id

        for oid, cd in cats_dict.items():
            if not cd.get('parent_id'):
                create_cat_recursive(oid, None)

    # Step 3: Brands
    log.info("Step 3: Creating brands...")
    if brands_table:
        cols = structure[brands_table]
        cursor.execute(f"SELECT * FROM {brands_table}")
        for row in cursor.fetchall():
            d = dict(zip(cols, row))
            name = (d.get('brand') or d.get('name') or '').strip()
            country = d.get('country') or ''
            if name:
                old_id = d.get('id')
                new_id = create_brand(name, country, api_url)
                if new_id and old_id:
                    brands_map[old_id] = new_id
                time.sleep(0.2)

    # Step 4: Products
    log.info("Step 4: Migrating products...")
    if not products_table:
        conn.close()
        raise Exception("Products table not found in SQLite")

    pcols = structure[products_table]
    cursor.execute(f"SELECT * FROM {products_table}")
    all_products = cursor.fetchall()

    # Set total for progress
    progress.update(migrating_total=len(all_products))

    local_product_names = set()
    for row in all_products:
        d = dict(zip(pcols, row))
        name = d.get('name') or d.get('fullName', '').strip()
        if name:
            local_product_names.add(name.strip().lower())

    # Load product properties
    props_dict = {}
    if props_table:
        pcols2 = structure[props_table]
        cursor.execute(f"SELECT * FROM {props_table}")
        for row in cursor.fetchall():
            d = dict(zip(pcols2, row))
            pid = d.get('product_id')
            if pid:
                props_dict.setdefault(pid, []).append(d)

    conn.close()

    # Load existing products cache
    load_existing_products(api_url)

    def process_single_product(product_row):
        try:
            pd = dict(zip(pcols, product_row))
            old_brand_id = pd.get('brand_id')
            old_category_id = pd.get('category_id')
            old_product_id = pd.get('id')

            product_id = create_product(pd, old_brand_id, old_category_id, api_url, progress)

            if product_id:
                pname = pd.get('name') or pd.get('fullName', '').strip()

                # Image
                img = pd.get('img') or pd.get('image') or pd.get('image_url')
                if img:
                    existing_media = get_product_media(product_id, api_url)
                    has_local = any(
                        m.get('url', '').startswith('/uploads/products/')
                        for m in existing_media if m.get('media_type') == 'image'
                    )
                    if not has_local:
                        add_product_image(product_id, str(img), api_url)
                        time.sleep(0.1)

                # Characteristics
                if old_product_id and old_product_id in props_dict:
                    existing_chars = get_product_characteristics(product_id, api_url)
                    for prop in props_dict[old_product_id]:
                        pn = prop.get('property_name', '').strip()
                        pv = prop.get('property_value', '')
                        if pn and pn in characteristics_cache:
                            cid = characteristics_cache[pn]
                            if cid not in existing_chars:
                                add_product_characteristic(product_id, cid, pv, api_url)
                            time.sleep(0.1)

            return product_id
        except Exception as e:
            if progress:
                progress.append_migrating_error(str(e))
            return None

    # Parallel processing
    processed = 0
    total = len(all_products)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_single_product, row): row for row in all_products}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log.warning(f"Thread error: {e}")
            processed += 1
            if processed % 100 == 0:
                log.info(f"Migrated {processed}/{total} products")

    # Step 5: Deactivate missing products
    log.info("Step 5: Deactivating missing products...")
    if local_product_names:
        deactivate_missing_products(local_product_names, api_url, progress)

    log.info(f"Migration complete. Products: {processed}, Categories: {len(categories_map)}, Brands: {len(brands_map)}")


if __name__ == '__main__':
    from .progress import ImportProgress
    p = ImportProgress()
    run_migration(p)
