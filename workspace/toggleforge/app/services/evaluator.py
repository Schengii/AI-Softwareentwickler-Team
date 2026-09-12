"""Evaluierungs-Engine für Feature-Flags und Canary-Rollouts."""

import hashlib
from typing import Any

from app.db import FeatureFlag, TargetingRule
from app.schemas import EvaluateResponse


def compute_percentage_bucket(flag_key: str, entity_id: str) -> int:
    """
    Berechnet einen deterministischen Prozentwert (0-99) via SHA256-Hashing.
    ADR-0001: Consistent Hashing über (flag_key + ':' + entity_id).
    """
    payload = f"{flag_key}:{entity_id}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    # 8 Hex-Zeichen = 32-Bit Integer
    return int(digest[:8], 16) % 100


def evaluate_targeting_rule(rule: TargetingRule, attributes: dict[str, Any], entity_id: str) -> bool:
    """
    Prüft, ob eine Targeting-Regel auf die gegebenen Attribute zutrifft.
    Unterstützt Operatoren: equals, in, not_in, contains.
    """
    attr_name = rule.attribute_name
    op = rule.operator.lower().strip()
    rule_values_raw = rule.values

    # Attribut-Wert ermitteln (auch entity_id / user_id unterstützen)
    actual_value = attributes.get(attr_name)
    if actual_value is None:
        if attr_name in ("user_id", "entity_id"):
            actual_value = entity_id
        elif attr_name == "email_domain" and "email" in attributes:
            email_parts = str(attributes["email"]).split("@")
            if len(email_parts) == 2:
                actual_value = f"@{email_parts[1]}"

    if actual_value is None:
        return False

    actual_str = str(actual_value).strip().lower()
    expected_list = [v.strip().lower() for v in rule_values_raw.split(",") if v.strip()]

    if op == "equals":
        return actual_str == rule_values_raw.strip().lower()
    elif op == "in":
        return actual_str in expected_list
    elif op == "not_in":
        return actual_str not in expected_list
    elif op == "contains":
        return rule_values_raw.strip().lower() in actual_str
    return False


def evaluate_flag(flag: FeatureFlag | None, entity_id: str | None, attributes: dict[str, Any] | None) -> EvaluateResponse:
    """
    Evaluiert ein Feature-Flag basierend auf Typ, Rollout-Prozentsatz oder Targeting-Regeln.
    """
    if flag is None:
        return EvaluateResponse(
            flag_key="unknown",
            enabled=False,
            reason="flag_not_found"
        )

    key = flag.key
    resolved_entity = entity_id or (attributes.get("user_id") if attributes else None) or "anonymous"
    attrs = attributes or {}

    # 1. Boolean Flag
    if flag.flag_type == "boolean":
        return EvaluateResponse(
            flag_key=key,
            enabled=flag.enabled,
            reason="boolean_flag" if flag.enabled else "boolean_flag_disabled"
        )

    # 2. Percentage Rollout
    elif flag.flag_type == "percentage":
        if not flag.enabled:
            return EvaluateResponse(
                flag_key=key,
                enabled=False,
                reason="flag_disabled"
            )
        bucket = compute_percentage_bucket(key, resolved_entity)
        is_active = bucket < flag.rollout_percentage
        return EvaluateResponse(
            flag_key=key,
            enabled=is_active,
            reason="percentage_rollout_match" if is_active else "percentage_rollout_miss"
        )

    # 3. Targeting Rules
    elif flag.flag_type == "targeting":
        if not flag.enabled:
            return EvaluateResponse(
                flag_key=key,
                enabled=False,
                reason="flag_disabled"
            )

        # Sortierte Regeln durchlaufen (Priorität aufsteigend)
        rules = sorted(flag.targeting_rules, key=lambda r: r.priority) if flag.targeting_rules else []
        for rule in rules:
            if evaluate_targeting_rule(rule, attrs, resolved_entity):
                return EvaluateResponse(
                    flag_key=key,
                    enabled=rule.enabled,
                    reason=f"targeting_match:{rule.attribute_name}"
                )

        # Fallback auf Flag-Default
        return EvaluateResponse(
            flag_key=key,
            enabled=False,
            reason="targeting_fallback_default"
        )

    return EvaluateResponse(
        flag_key=key,
        enabled=flag.enabled,
        reason="unknown_type_default"
    )
