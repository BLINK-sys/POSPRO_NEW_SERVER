from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
jwt = JWTManager()

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Устанавливаем кодировку UTF-8 для PostgreSQL соединений"""
    if 'postgresql' in str(dbapi_connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET client_encoding = 'UTF8'")
            cursor.execute("SET NAMES 'utf8'")
        except Exception as e:
            print(f"Ошибка при установке кодировки: {e}")
        finally:
            cursor.close()
