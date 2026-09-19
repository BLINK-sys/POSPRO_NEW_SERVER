from .user import User
from .product import Product
from .category import Category
from .characteristic import ProductCharacteristic
from .characteristics_list import CharacteristicsList
from .media import ProductMedia
from .documents import ProductDocument
from .brand import Brand
from .status import Status
from .favorite import Favorite
from .cart import Cart
from .order import Order, OrderItem
from .order_status import OrderStatus
from .order_manager import OrderManager
from .systemuser import SystemUser
from .kp_settings import KPSettings
from .site_visitor import SiteVisitor
from .site_request import SiteRequest
from .product_view import ProductView
from .currency import Currency
from .warehouse import Warehouse, WarehouseVariable, WarehouseFormula
from .product_warehouse_cost import ProductWarehouseCost
from .help_article import HelpArticle, HelpArticleMedia
from .driver import Driver
from .ai_logs import AIImportLog, AIChatSession, AIChatMessage
from .kp_share import KPShare, KPSuperAdminAccess
from .kp_client import KpClient
from .search_page import SearchPageSettings, SearchPageCategory, SearchPageBrand
from .integration import IntegrationSettings, IntegrationRun, IntegrationCommand
from .collector import CollectorTask, CollectorFile, CollectorCommand, CollectorWorker
from .category_alias import CategoryAlias
from .section_card import SectionCard, SectionCardCategory
from .customer_activity import CustomerActivity

# CRM (Сделки/Задачи/Чат) — этап 1 (2026-09-19). Модели описаны в
# `PosPro/Магазин PosPro/Доменные области/31 CRM и двумодовая навигация (планирование).md`.
from .deal_pipeline import DealPipeline, DealStage
from .deal import Deal, DealMember, DealKp, DealOrder, DealActivity
from .task import Task, TaskMember, TaskChecklist, TaskActivity
from .chat import ChatRoom, ChatMember, ChatMessage, ChatReaction, ChatAttachment
from .entity_attachment import EntityAttachment
from .crm_ingest_source import CrmIngestSource
from .notification import Notification, WebPushSubscription, UserPresence
