from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.database import Base


class ExportHistory(Base):
    __tablename__ = "export_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(20), nullable=False)  # 'CSV' oder 'PDF'
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    file_path = Column(String(255), nullable=False)
