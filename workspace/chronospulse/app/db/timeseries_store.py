"""
ChronosPulse - Zeitreihen- & Observability-Persistenz-Layer
Kombiniert SQLite (OLTP / WAL-Modus) für Live-Ingestion mit DuckDB (OLAP)
für zeitbasierte Partitionierung, Indexierung und Metrik-Aggregationen (Latenz, Error-Rate, Durchsatz).
"""

from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


# ============================================================================
# 1. SQLAlchemy ORM-Basis & Modelle (OLTP - Single-DB Async)
# ============================================================================

class Base(DeclarativeBase):
    """Zentrale DeclarativeBase für alle SQLAlchemy-Modelle im Projekt."""
    pass


class MetricEvent(Base):
    """
    Speichert eingehende Metrik- und Observability-Events.
    Hochperformant indiziert über (service_name, timestamp) und (metric_name, timestamp).
    """
    __tablename__ = "metric_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, default="ok", nullable=False)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    metadata_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)

    # Zusammengesetzte Indizes für zeitbasierte Abfragen
    __table_args__ = (
        Index("ix_metric_service_time", "service_name", "timestamp"),
        Index("ix_metric_name_time", "metric_name", "timestamp"),
        Index("ix_metric_status_time", "status", "timestamp"),
    )


class AnomalyIncident(Base):
    """
    Persistiert erkannte Anomalien und Incident-Status.
    """
    __tablename__ = "anomaly_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), index=True, default="warning", nullable=False)
    detected_at: Mapped[float] = mapped_column(Float, index=True, nullable=False)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=None)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        Index("ix_anomaly_service_time", "service_name", "detected_at"),
        Index("ix_anomaly_severity", "severity", "detected_at"),
    )


# ============================================================================
# 2. Pydantic v2 Schemas
# ============================================================================

class MetricIngestSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str
    service_name: str
    metric_name: str
    metric_value: float = Field(..., description="Messwert (z.B. Latenz in ms, Durchsatz ops/s)")
    timestamp: float = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).timestamp())
    status: str = Field(default="ok")
    tags_json: Optional[str] = None
    metadata_payload: Optional[str] = None


class AggregatedMetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    bucket_start: str
    service_name: str
    metric_name: str
    count: int
    avg_value: float
    min_value: float
    max_value: float
    p95_value: float
    p99_value: float


# ============================================================================
# 3. Dual-Engine Storage Manager (SQLite Async Engine + DuckDB Analytics)
# ============================================================================

class ChronosStorageManager:
    """
    Verwaltet SQLite für asynchrone Ingestion und DuckDB für partitions-basierte
    Zeitreihen-Aggregationen (Latenz, Error-Rate, Durchsatz) und Parquet-Exporte.
    """

    def __init__(
        self,
        sqlite_url: str = "sqlite+aiosqlite:///./data/chronospulse.db",
        duckdb_path: str = "./data/chronospulse_analytics.duckdb",
        parquet_dir: str = "./data/partitions",
        is_testing: bool = False,
    ):
        self.sqlite_url = sqlite_url
        self.duckdb_path = duckdb_path
        self.parquet_dir = Path(parquet_dir)
        self.is_testing = is_testing

        # Verzeichnisse anlegen falls Dateisystem-basiert
        if not sqlite_url.startswith("sqlite+aiosqlite:///:memory:"):
            db_path = sqlite_url.replace("sqlite+aiosqlite:///", "")
            if "/" in db_path:
                os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        if duckdb_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(duckdb_path)), exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)

        # Async Engine Konfiguration
        engine_kwargs: Dict[str, Any] = {"echo": False}
        if ":memory:" in sqlite_url:
            engine_kwargs["poolclass"] = StaticPool

        self.engine: AsyncEngine = create_async_engine(self.sqlite_url, **engine_kwargs)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # DuckDB Verbindung für analytische Abfragen
        self._duckdb_conn: Optional[duckdb.DuckDBPyConnection] = None

    def get_duckdb(self) -> duckdb.DuckDBPyConnection:
        """Liefert die DuckDB-Verbindung und initialisiert Tabellen."""
        if self._duckdb_conn is None:
            self._duckdb_conn = duckdb.connect(self.duckdb_path)
            self._init_duckdb_schema()
        return self._duckdb_conn

    def _init_duckdb_schema(self) -> None:
        """Initialisiert analytische Partitionstabellen und Views in DuckDB."""
        conn = self._duckdb_conn
        assert conn is not None

        # Tabellenschema für analytische Events
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics_events (
                event_id VARCHAR,
                service_name VARCHAR,
                metric_name VARCHAR,
                metric_value DOUBLE,
                timestamp DOUBLE,
                status VARCHAR,
                event_date DATE,
                event_hour INTEGER
            )
        """)

        # Indizes auf Zeitreihen & Service
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_duck_service_metric 
            ON analytics_events (service_name, metric_name, event_date);
        """)

    async def init_sqlite_db(self) -> None:
        """Initialisiert das SQLite-Schema asynchron."""
        async with self.engine.begin() as conn:
            # WAL-Modus aktivieren für hohe Concurrency
            if "sqlite" in self.sqlite_url and ":memory:" not in self.sqlite_url:
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                await conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            await conn.run_sync(Base.metadata.create_all)

    async def insert_metrics_batch(self, metrics: List[MetricIngestSchema]) -> int:
        """
        Fügt Metriken asynchron in SQLite ein und spiegelt sie in DuckDB für OLAP.
        """
        if not metrics:
            return 0

        async with self.session_factory() as session:
            async with session.begin():
                db_objs = [
                    MetricEvent(
                        event_id=m.event_id,
                        service_name=m.service_name,
                        metric_name=m.metric_name,
                        metric_value=m.metric_value,
                        timestamp=m.timestamp,
                        status=m.status,
                        tags_json=m.tags_json,
                        metadata_payload=m.metadata_payload,
                    )
                    for m in metrics
                ]
                session.add_all(db_objs)

        # In DuckDB einfügen für Partitioning & Aggregation
        conn = self.get_duckdb()
        records = []
        for m in metrics:
            dt = datetime.datetime.fromtimestamp(m.timestamp, tz=datetime.timezone.utc)
            records.append((
                m.event_id,
                m.service_name,
                m.metric_name,
                m.metric_value,
                m.timestamp,
                m.status,
                dt.date(),
                dt.hour,
            ))

        conn.executemany("""
            INSERT INTO analytics_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, records)

        return len(metrics)

    def partition_and_export_parquet(self, partition_by: str = "event_date") -> str:
        """
        Partitioniert Metriken zeitbasiert und exportiert sie in Parquet-Partitionen.
        Beispiel-Zielstruktur: data/partitions/event_date=YYYY-MM-DD/*.parquet
        """
        conn = self.get_duckdb()
        target_path = str(self.parquet_dir / "partitioned_metrics")
        conn.execute(f"""
            COPY analytics_events TO '{target_path}' 
            (FORMAT PARQUET, PARTITION_BY ({partition_by}), OVERWRITE_OR_IGNORE 1)
        """)
        return target_path

    def query_time_bucket_metrics(
        self,
        service_name: str,
        metric_name: str,
        start_ts: float,
        end_ts: float,
        bucket_seconds: int = 60,
    ) -> List[AggregatedMetricResult]:
        """
        Führt zeitreihenbasierte Bucketing- und Percentile-Aggregationen mit DuckDB aus.
        Ermittelt Durchsatz, Avg, Min, Max, p95 und p99.
        """
        conn = self.get_duckdb()
        query = """
            SELECT 
                strftime(to_timestamp(floor(timestamp / ?) * ?), '%Y-%m-%d %H:%M:%S') AS bucket_start,
                service_name,
                metric_name,
                count(*) AS cnt,
                avg(metric_value) AS avg_val,
                min(metric_value) AS min_val,
                max(metric_value) AS max_val,
                quantile_cont(metric_value, 0.95) AS p95_val,
                quantile_cont(metric_value, 0.99) AS p99_val
            FROM analytics_events
            WHERE service_name = ? 
              AND metric_name = ?
              AND timestamp >= ? 
              AND timestamp <= ?
            GROUP BY 1, 2, 3
            ORDER BY 1 ASC
        """
        cursor = conn.execute(query, [bucket_seconds, bucket_seconds, service_name, metric_name, start_ts, end_ts])
        rows = cursor.fetchall()

        results: List[AggregatedMetricResult] = []
        for r in rows:
            results.append(
                AggregatedMetricResult(
                    bucket_start=r[0],
                    service_name=r[1],
                    metric_name=r[2],
                    count=int(r[3]),
                    avg_value=round(float(r[4]), 4),
                    min_value=round(float(r[5]), 4),
                    max_value=round(float(r[6]), 4),
                    p95_value=round(float(r[7]), 4),
                    p99_value=round(float(r[8]), 4),
                )
            )
        return results

    def query_service_error_rate(
        self,
        service_name: str,
        start_ts: float,
        end_ts: float,
    ) -> Dict[str, Any]:
        """
        Berechnet die Error-Rate und den Gesamtdurchsatz für einen Dienst.
        """
        conn = self.get_duckdb()
        query = """
            SELECT 
                count(*) AS total_events,
                count(CASE WHEN status != 'ok' THEN 1 END) AS error_events,
                coalesce(count(CASE WHEN status != 'ok' THEN 1 END) * 1.0 / NULLIF(count(*), 0), 0.0) AS error_rate,
                avg(metric_value) AS avg_latency
            FROM analytics_events
            WHERE service_name = ?
              AND timestamp >= ?
              AND timestamp <= ?
        """
        cursor = conn.execute(query, [service_name, start_ts, end_ts])
        row = cursor.fetchone()
        if not row:
            return {"service_name": service_name, "total_events": 0, "error_events": 0, "error_rate": 0.0, "avg_latency": 0.0}

        return {
            "service_name": service_name,
            "total_events": int(row[0]),
            "error_events": int(row[1]),
            "error_rate": round(float(row[2]), 4),
            "avg_latency": round(float(row[3] or 0.0), 4),
        }

    async def close(self) -> None:
        """Schließt alle SQLite und DuckDB Ressourcen."""
        if self._duckdb_conn is not None:
            self._duckdb_conn.close()
            self._duckdb_conn = None
        await self.engine.dispose()
