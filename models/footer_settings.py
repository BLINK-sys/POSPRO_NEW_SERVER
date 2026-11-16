from extensions import db


class FooterSetting(db.Model):
    __tablename__ = 'footer_settings'

    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text)
    instagram_url = db.Column(db.String(255))
    whatsapp_url = db.Column(db.String(255))
    telegram_url = db.Column(db.String(255))
    phone = db.Column(db.String(100))
    email = db.Column(db.String(255))
    address = db.Column(db.String(255))
    working_hours = db.Column(db.String(255))

    # ─── Юридические реквизиты (блок для подвала и страницы /requisites) ───
    # Выводятся кратким блоком в подвале (юрлицо, БИН, адрес) и в полном
    # объёме — на статической странице «Реквизиты».
    legal_name = db.Column(db.String(255))
    bin_number = db.Column(db.String(32))
    legal_address = db.Column(db.String(500))
    bank_name = db.Column(db.String(255))
    bank_bic = db.Column(db.String(32))
    bank_iik = db.Column(db.String(64))
    bank_kbe = db.Column(db.String(8))

    # ─── Порядок элементов в колонках подвала ─────────────────────────────
    # JSON-строка с массивом ключей в нужном порядке.
    # Контакты: ["address","phone","email","working_hours"].
    # Информация: slug'и StaticPage в нужном порядке + спец-ключи
    # "offer","privacy" (это тоже static_page slugs).
    # NULL / пусто = дефолтный порядок, зашитый во фронте.
    contacts_order = db.Column(db.Text)
    info_order = db.Column(db.Text)
