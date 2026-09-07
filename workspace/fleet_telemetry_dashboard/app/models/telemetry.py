import enum

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)

from app.db.session import Base


class VehicleStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"

class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True, index=True)
    vin = Column(String, unique=True, nullable=False, index=True)
    model = Column(String, nullable=False)
    status = Column(Enum(VehicleStatus), default=VehicleStatus.OFFLINE, nullable=False)
    created_at = Column(DateTime, default=func.now())

class Telemetry(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=func.now(), index=True)
    speed = Column(Float)
    fuel_level = Column(Float)
    engine_temp = Column(Float)
    diagnostics = Column(JSON, nullable=True, default=None)
