import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional
from app.database import get_all_alert_rules_db, save_alert_rule_db, delete_alert_rule_db
from app.models.schemas import AlertEvent, AlertRule, AlertRuleCreate, WindowAggregate
from app.services.aggregator import aggregator_service
from app.services.pubsub import pubsub_manager

logger = logging.getLogger(__name__)


class AlertEngine:
    """Dynamische Rule-Engine für Schwellwert-Alerts basierend auf Metrik-Aggregationen."""

    def __init__(self) -> None:
        self.rules: Dict[str, AlertRule] = {}
        self.active_alerts: Dict[str, AlertEvent] = {}

    async def load_rules(self) -> None:
        """Lädt alle gespeicherten Regeln aus der Datenbank."""
        try:
            db_rules = await get_all_alert_rules_db()
            for rule in db_rules:
                self.rules[rule.id] = rule
        except Exception as e:  # noqa: BLE001 - Fallback falls DB noch nicht initialisiert
            logger.warning(f"Konnte Regeln nicht aus DB laden: {e}")

    async def add_rule(self, rule_in: AlertRuleCreate) -> AlertRule:
        """Fügt eine neue Alert-Regel hinzu und speichert sie persistent."""
        rule_id = rule_in.id or str(uuid.uuid4())
        rule = AlertRule(
            id=rule_id,
            name=rule_in.name,
            metric_name=rule_in.metric_name,
            aggregation=rule_in.aggregation,
            condition=rule_in.condition,
            threshold=rule_in.threshold,
            window_seconds=rule_in.window_seconds,
            enabled=rule_in.enabled,
            created_at=time.time(),
        )
        self.rules[rule.id] = rule
        await save_alert_rule_db(rule)
        return rule

    async def remove_rule(self, rule_id: str) -> bool:
        """Löscht eine Alert-Regel persistent."""
        if rule_id in self.rules:
            del self.rules[rule_id]
        return await delete_alert_rule_db(rule_id)

    def get_rules(self) -> List[AlertRule]:
        """Gibt alle registrierten Alert-Regeln zurück."""
        return list(self.rules.values())

    async def evaluate_metric(self, metric_name: str) -> List[AlertEvent]:
        """Evaluiert alle aktiven Regeln für die gegebene Metrik."""
        triggered_events: List[AlertEvent] = []
        rules_to_check = [r for r in self.rules.values() if r.enabled and r.metric_name == metric_name]

        for rule in rules_to_check:
            agg: WindowAggregate = aggregator_service.get_aggregate(rule.metric_name, rule.window_seconds)
            current_val = getattr(agg, rule.aggregation, None)
            if current_val is None:
                continue

            is_breached = self._check_condition(current_val, rule.condition, rule.threshold)

            if is_breached:
                event = AlertEvent(
                    id=str(uuid.uuid4()),
                    rule_id=rule.id,
                    rule_name=rule.name,
                    metric_name=rule.metric_name,
                    current_value=float(current_val),
                    threshold=float(rule.threshold),
                    condition=rule.condition,
                    triggered_at=time.time(),
                    status="firing",
                )
                self.active_alerts[rule.id] = event
                triggered_events.append(event)
                # Broadcast via WebSocket
                await pubsub_manager.broadcast({
                    "type": "alert",
                    "data": event.model_dump(),
                })
            else:
                # Falls Alert zuvor feuerte, auflösen
                if rule.id in self.active_alerts:
                    resolved_event = AlertEvent(
                        id=str(uuid.uuid4()),
                        rule_id=rule.id,
                        rule_name=rule.name,
                        metric_name=rule.metric_name,
                        current_value=float(current_val),
                        threshold=float(rule.threshold),
                        condition=rule.condition,
                        triggered_at=time.time(),
                        status="resolved",
                    )
                    del self.active_alerts[rule.id]
                    triggered_events.append(resolved_event)
                    await pubsub_manager.broadcast({
                        "type": "alert_resolved",
                        "data": resolved_event.model_dump(),
                    })

        return triggered_events

    def _check_condition(self, val: float, cond: str, threshold: float) -> bool:
        """Vergleicht den aktuellen Wert mit dem Schwellwert."""
        c = cond.lower().strip()
        if c in ("gt", ">"):
            return val > threshold
        elif c in ("gte", ">="):
            return val >= threshold
        elif c in ("lt", "<"):
            return val < threshold
        elif c in ("lte", "<="):
            return val <= threshold
        elif c in ("eq", "=="):
            return math.isclose(val, threshold, rel_tol=1e-5)
        elif c in ("ne", "!="):
            return not math.isclose(val, threshold, rel_tol=1e-5)
        return False


# Singleton-Instanz laut Schnittstellenvertrag
alert_engine = AlertEngine()
