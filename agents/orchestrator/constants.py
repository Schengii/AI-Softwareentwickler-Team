"""
agents/orchestrator/constants.py – Modul-Konstanten, die von mehreren Orchestrator-Mixins
gemeinsam gebraucht werden (kein zirkulärer Import zwischen den Mixin-Modulen und dem
zusammensetzenden agents/orchestrator/__init__.py).
"""

from collections.abc import Awaitable, Callable

from core.message_bus import AgentTask

# Reine Prüf-/Berichts-Agenten: sollen bestehenden Code LESEN und bewerten, aber nicht
# selbst umschreiben (das ist Aufgabe von refactoring/backend/etc.) – spart nebenbei auch
# Tokens, da ihnen ein kleineres Werkzeug-Set (kein write_file/edit_file/run_command) angeboten wird.
REVIEW_ONLY_AGENT_IDS = {"code_reviewer", "compliance", "project_cleaner"}

StatusCallback = Callable[[str], None]

# Optionaler Aufrufer-Hook: bekommt den zerlegten Plan (Zusammenfassung, Projekt-Ordnername,
# vollständige Teilaufgaben-Liste) NACH TaskManager.decompose(), aber VOR jeder Ausführung
# (kein Agent hat zu diesem Zeitpunkt bereits Tokens verbraucht) und entscheidet per Rückgabe-
# wert, ob der Lauf fortgesetzt wird. None (Standard) = kein Gate, unverändertes Verhalten -
# nur interface/cli.py reicht aktuell einen echten Callback durch (Dashboard/MCP bleiben
# dadurch bewusst nicht-interaktiv, siehe config.ENABLE_PLAN_CONFIRMATION).
PlanConfirmationCallback = Callable[[str, str, list[AgentTask]], Awaitable[bool]]

# Reihenfolge & Anzeige der 6 Fachbereichs-Phasen. Die Mitgliederlisten stammen
# zentral aus DEPARTMENT_DEFINITIONS (agents/department_lead_agent.py), damit
# Orchestrator und Teamleiter-Prompts nie auseinanderlaufen können.
#
# Design-vor-Dev: UI/UX, Design-Tokens und visuelle Assets (design_lead) werden
# VOR der Software-Entwicklung (dev_lead) erstellt, damit Entwickler diese direkt
# einbinden können. Dokumentation, i18n und Barrierefreiheit (content_lead) laufen
# NACH der Entwicklung auf dem tatsächlich erzeugten Code.
PHASE_ORDER = [
    ("planning_lead",   "Fachbereich 1/6: Planung & Architektur", "👔", "sequential"),
    ("design_lead",     "Fachbereich 2/6: UI/UX, Design & Media", "🎨", "parallel"),
    ("dev_lead",        "Fachbereich 3/6: Software-Entwicklung", "⚡", "parallel"),
    ("content_lead",    "Fachbereich 4/6: Content, Doku & Barrierefreiheit", "📚", "parallel"),
    ("qa_lead",         "Fachbereich 5/6: Qualität & Security", "🛡️", "parallel"),
    ("governance_lead", "Fachbereich 6/6: Review & Governance", "🔍", "sequential"),
]
