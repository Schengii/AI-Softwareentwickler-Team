"""Tests für Attribut-Targeting und Regel-Operatoren."""

from app.db import FeatureFlag, TargetingRule
from app.services.evaluator import evaluate_flag, evaluate_targeting_rule


def test_operator_equals():
    """Prüft den 'equals'-Operator."""
    rule = TargetingRule(attribute_name="tier", operator="equals", values="gold", enabled=True)
    assert evaluate_targeting_rule(rule, {"tier": "gold"}, "u1") is True
    assert evaluate_targeting_rule(rule, {"tier": "silver"}, "u1") is False


def test_operator_in():
    """Prüft den 'in'-Operator bei Listeneinträgen."""
    rule = TargetingRule(attribute_name="country", operator="in", values="DE, AT, CH", enabled=True)
    assert evaluate_targeting_rule(rule, {"country": "DE"}, "u1") is True
    assert evaluate_targeting_rule(rule, {"country": "at"}, "u1") is True
    assert evaluate_targeting_rule(rule, {"country": "FR"}, "u1") is False


def test_operator_not_in():
    """Prüft den 'not_in'-Operator."""
    rule = TargetingRule(attribute_name="role", operator="not_in", values="guest, blocked", enabled=True)
    assert evaluate_targeting_rule(rule, {"role": "admin"}, "u1") is True
    assert evaluate_targeting_rule(rule, {"role": "guest"}, "u1") is False


def test_operator_contains():
    """Prüft den 'contains'-Operator."""
    rule = TargetingRule(attribute_name="email", operator="contains", values="@acme.org", enabled=True)
    assert evaluate_targeting_rule(rule, {"email": "john@acme.org"}, "u1") is True
    assert evaluate_targeting_rule(rule, {"email": "john@other.com"}, "u1") is False


def test_email_domain_automatic_resolution():
    """Prüft die automatische Extraktion der E-Mail-Domain."""
    rule = TargetingRule(attribute_name="email_domain", operator="equals", values="@internal.team", enabled=True)
    assert evaluate_targeting_rule(rule, {"email": "dev@internal.team"}, "u1") is True
    assert evaluate_targeting_rule(rule, {"email": "dev@external.team"}, "u1") is False


def test_targeting_rules_priority_and_fallback():
    """Prüft, dass Regeln mit kleinerer Prioritätsnummer zuerst ausgewertet werden und Fallback greift."""
    rule_high_prio = TargetingRule(
        attribute_name="beta",
        operator="equals",
        values="true",
        enabled=True,
        priority=1,
    )
    rule_low_prio = TargetingRule(
        attribute_name="role",
        operator="equals",
        values="tester",
        enabled=False,
        priority=2,
    )

    flag = FeatureFlag(
        key="new_feature",
        flag_type="targeting",
        enabled=True,
        targeting_rules=[rule_low_prio, rule_high_prio],
    )

    # Match auf Regel mit Priorität 1
    res = evaluate_flag(flag, entity_id="u1", attributes={"beta": "true", "role": "tester"})
    assert res.enabled is True
    assert res.reason == "targeting_match:beta"

    # Match auf Fallback, wenn keine Regel zutrifft
    res_fallback = evaluate_flag(flag, entity_id="u2", attributes={"beta": "false", "role": "user"})
    assert res_fallback.enabled is False
    assert res_fallback.reason == "targeting_fallback_default"
