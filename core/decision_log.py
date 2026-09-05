"""
core/decision_log.py – Live, strukturiertes Entscheidungsprotokoll pro Projekt.

Realer Fund (Punkt 5 einer Team-Retrospektive): bisher waren die wesentlichen Entscheidungen
des Orchestrators während eines Laufs (welcher Fachbereich wurde warum zusätzlich eingeplant,
wann griff die Governance-Fix-Schleife, wann wurde ein Budget-Abbruch ausgelöst) nur aus dem
Text des Abschlussberichts oder - schlimmer - erst aus dem Code selbst rekonstruierbar. Dieses
Modul schreibt jede solche Entscheidung sofort, strukturiert (JSONL, ein Ereignis pro Zeile) in
`<project_dir>/.ai_team_decisions.jsonl` - lesbar sowohl während ein Lauf noch läuft (anders als
der erst am Ende geschriebene Abschlussbericht) als auch danach zur Nachvollziehbarkeit, ohne
dass jemand die Orchestrator-Quelldateien lesen muss, um zu verstehen, WARUM das Team etwas
Bestimmtes getan hat.

Bewusst KEIN Ersatz für core/project_status.py (das hält den AUSGANG eines ganzen Laufs fest,
über Läufe hinweg) - dieses Modul hält die EINZELNEN Zwischenentscheidungen INNERHALB eines
Laufs fest, append-only, best-effort (ein Schreibfehler hier darf einen laufenden Team-Lauf
niemals zum Absturz bringen).
"""

import json
import os
from datetime import UTC, datetime

DECISION_LOG_FILENAME = ".ai_team_decisions.jsonl"
MAX_DECISIONS_SHOWN = 20

# Team-Optimierung (Retrospektive 2026-09-05): mehrere Aufrufstellen (unresolved_governance_
# critical_ticket_opened, recurring_failure_ticket_opened, ...) kürzten `detail` schon VOR dem
# Aufruf hier auf 300 Zeichen, zusätzlich zum bisherigen 500-Zeichen-Cap unten - beide Grenzen
# lagen unter der Länge eines echten mehrzeiligen Governance-/Testfehler-Berichts und schnitten
# ihn dadurch mitten im Satz ab. Anders als core/project_status.py (dort existiert bereits ein
# ungekürztes Vollprotokoll, .ai_team_status_full.log, als Fallback) gibt es für dieses Log
# KEINE Vollversion - eine hier verlorene Information ist unwiederbringlich weg, sowohl für
# menschliche Post-Mortems als auch für eine künftige automatische Lern-Extraktion aus
# wiederkehrenden Fehlschlägen. Einzelnes, deutlich großzügigeres Limit statt der bisherigen
# zwei inkonsistenten Werte - die Aufrufstellen kürzen nicht mehr selbst.
MAX_DETAIL_CHARS = 4000


def log_decision(project_dir: str, event: str, detail: str, **extra) -> None:
    """Hängt eine Entscheidung an. `event` ist ein kurzer, stabiler Kategorie-Slug (z.B.
    "architect_forced_reescalation", "governance_fix_dispatched", "budget_aborted") - kein
    Freitext, damit spätere Auswertung (z.B. core/optimization_advisor.py) danach filtern
    könnte, ohne Text-Heuristiken zu brauchen."""
    try:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "detail": detail[:MAX_DETAIL_CHARS],
            **extra,
        }
        path = os.path.join(project_dir, DECISION_LOG_FILENAME)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_decisions(project_dir: str, limit: int = MAX_DECISIONS_SHOWN) -> list[dict]:
    """Neueste zuerst. Leere Liste, wenn noch keine Entscheidung protokolliert wurde oder die
    Datei nicht lesbar ist (z.B. ein noch nicht existierendes Projektverzeichnis)."""
    path = os.path.join(project_dir, DECISION_LOG_FILENAME)
    if not os.path.exists(path):
        return []
    decisions = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    decisions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return decisions[-limit:][::-1]
