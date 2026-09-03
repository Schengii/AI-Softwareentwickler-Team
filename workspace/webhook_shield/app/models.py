import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./webhookshield.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(Integer, primary_key=True, index=True)
    endpoint_path = Column(String, unique=True, nullable=False)
    hmac_secret = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class DeliveryLog(Base):
    __tablename__ = "delivery_logs"
    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), index=True)
    payload_json = Column(JSON, nullable=False)
    headers_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False)
    retry_count = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)
