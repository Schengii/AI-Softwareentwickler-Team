import json
import os
import aiosqlite
from typing import Any, Dict, List, Optional
from app.models.schemas import AlertRule, MetricItem

DB_PATH = os.getenv("DATABASE_PATH", "metrics.db")


async def init_db():
    """Initialisiert die SQLite-Datenbanktabellen für Metriken und Alert-Regeln."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp REAL NOT NULL,
                tags TEXT,
                is_error INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                aggregation TEXT NOT NULL,
                condition TEXT NOT NULL,
                threshold REAL NOT NULL,
                window_seconds REAL NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_events (
                id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                current_value REAL NOT NULL,
                threshold REAL NOT NULL,
                condition TEXT NOT NULL,
                triggered_at REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)
        await db.commit()


async def save_metric_db(metric: MetricItem):
    """Speichert eine Metrik persistent in die SQLite-Datenbank."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO metrics (name, value, timestamp, tags, is_error) VALUES (?, ?, ?, ?, ?)",
            (
                metric.name,
                metric.value,
                metric.timestamp,
                json.dumps(metric.tags),
                1 if metric.is_error else 0
            )
        )
        await db.commit()


async def save_metrics_batch_db(metrics: List[MetricItem]):
    """Speichert einen Batch von Metriken persistent in die SQLite-Datenbank."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO metrics (name, value, timestamp, tags, is_error) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    m.name,
                    m.value,
                    m.timestamp,
                    json.dumps(m.tags),
                    1 if m.is_error else 0
                )
                for m in metrics
            ]
        )
        await db.commit()


async def save_alert_rule_db(rule: AlertRule):
    """Speichert oder aktualisiert eine Alert-Regel in der SQLite-Datenbank."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO alert_rules (id, name, metric_name, aggregation, condition, threshold, window_seconds, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name,
                   metric_name=excluded.metric_name,
                   aggregation=excluded.aggregation,
                   condition=excluded.condition,
                   threshold=excluded.threshold,
                   window_seconds=excluded.window_seconds,
                   enabled=excluded.enabled
            """,
            (
                rule.id,
                rule.name,
                rule.metric_name,
                rule.aggregation,
                rule.condition,
                rule.threshold,
                rule.window_seconds,
                1 if rule.enabled else 0,
                rule.created_at
            )
        )
        await db.commit()


async def get_all_alert_rules_db() -> List[AlertRule]:
    """Lädt alle gespeicherten Alert-Regeln aus der Datenbank."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alert_rules") as cursor:
            rows = await cursor.fetchall()
            return [
                AlertRule(
                    id=row["id"],
                    name=row["name"],
                    metric_name=row["metric_name"],
                    aggregation=row["aggregation"],
                    condition=row["condition"],
                    threshold=row["threshold"],
                    window_seconds=row["window_seconds"],
                    enabled=bool(row["enabled"]),
                    created_at=row["created_at"]
                )
                for row in rows
            ]


async def delete_alert_rule_db(rule_id: str) -> bool:
    """Löscht eine Alert-Regel aus der Datenbank."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        await db.commit()
        return cursor.rowcount > 0
