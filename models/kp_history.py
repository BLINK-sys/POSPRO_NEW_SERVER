from extensions import db
from datetime import datetime


class KPHistory(db.Model):
    __tablename__ = 'kp_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    user_role = db.Column(db.String(20), nullable=False, default='admin')
    name = db.Column(db.String(255), nullable=False, default='')
    items = db.Column(db.JSON, nullable=False, default=list)
    settings = db.Column(db.JSON, nullable=False, default=dict)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    calculator_data = db.Column(db.JSON, nullable=True)
    # Если задано — контракт подписан, КП заморожено. Любые изменения в
    # основном магазине (цены, курсы, vat_enabled складов) НЕ затрагивают
    # подписанные КП. Юзер может править строки руками и добавлять новые
    # товары — новые товары захватывают актуальные данные на момент
    # добавления и сразу попадают в снимок.
    signed_at = db.Column(db.DateTime, nullable=True)
    # Привязка к клиенту из адресной книги (kp_client). Не дублируем данные
    # клиента, ссылаемся только по id — менеджер правит карточку клиента,
    # все КП тут же подхватывают новые данные. ON DELETE RESTRICT на стороне
    # БД нет (мы проверяем приложением — даём более понятную ошибку).
    client_id = db.Column(db.Integer, db.ForeignKey('kp_client.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, short=False):
        result = {
            'id': self.id,
            'name': self.name,
            'total_amount': self.total_amount,
            'signed_at': self.signed_at.isoformat() if self.signed_at else None,
            'client_id': self.client_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        # Денормализованные данные клиента. В short-варианте (список карточек)
        # отдаём минимум — id/тип/display_name для чипа. В полном варианте
        # (загрузка КП в редактор) отдаём всё, чтобы фронт мог показать
        # popover «Инфо» с БИН/ФИО/телефоном без дополнительного запроса.
        if self.client_id:
            from models.kp_client import KpClient
            client = KpClient.query.get(self.client_id)
            if client:
                if short:
                    result['client'] = {
                        'id': client.id,
                        'organization_type': client.organization_type,
                        'display_name': client.display_name,
                    }
                else:
                    result['client'] = client.to_dict()
            else:
                # Если клиент удалён (что в норме невозможно — есть гард,
                # но защита от ручных правок БД) — просто null.
                result['client'] = None
        if not short:
            result['items'] = self.items
            result['settings'] = self.settings
            result['calculator_data'] = self.calculator_data
        return result
