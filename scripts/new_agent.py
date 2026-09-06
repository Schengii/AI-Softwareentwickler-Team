"""
scripts/new_agent.py – Scaffolding-Werkzeug für eine neue Fachrolle im Agenten-Team.

Nutzeranfrage (Team-Wachstums-Retrospektive 2026-09-06): jede der (inzwischen 33) Rollen ist
an VIER unabhängig gepflegten Stellen registriert - `agents/orchestrator/__init__.py`
(tatsächlich instanziierte Klasse), `core/task_manager.py.AVAILABLE_AGENTS` (Beschreibung für
den Planer), `config.py.AGENT_MODELS` (Modellstufe) und GENAU eine
`config.py.DEPARTMENT_*_AGENTS`-Menge (Fachbereichszugehörigkeit). Keine dieser vier Stellen
ist von den anderen automatisch ableitbar - `tests/test_agent_registry_consistency.py` prüft
nur, DASS sie zusammenpassen, verhindert das Vergessen einer Stelle aber nicht von vornherein.
Dieses Skript automatisiert alle vier Schritte plus das Anlegen der neuen Agentenklasse selbst
(siehe ARCHITECTURE.md Abschnitt 1.1 für die manuelle Variante/Erklärung jedes Schritts).

Die eigentlichen Text-Transformationen (`_insert_*`-Funktionen) arbeiten rein auf Strings -
ohne Dateizugriff - und sind deshalb isoliert testbar (siehe
tests/test_new_agent_scaffold.py), ohne echte Repo-Dateien zu berühren. main() ist die dünne
CLI-Schicht, die diese Funktionen auf die vier echten Dateien anwendet und anschließend
`ruff check --fix` (Import-Sortierung) sowie die Registry-Konsistenz-Tests laufen lässt.

Verwendung:
    python scripts/new_agent.py <agent_id> --name "Anzeigename" \\
        --description "Kurzbeschreibung für den Planer-Prompt" \\
        --phase 3 --department dev --tier standard

Danach: den generierten System-Prompt in `agents/<agent_id>_agent.py` ausformulieren (das
Skript legt nur ein Gerüst mit TODO-Markierungen an - eine gute Rollenbeschreibung erfordert
fachliches Wissen, das sich nicht sinnvoll generisch erzeugen lässt) und `git diff` prüfen.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR_INIT = REPO_ROOT / "agents" / "orchestrator" / "__init__.py"
TASK_MANAGER = REPO_ROOT / "core" / "task_manager.py"
CONFIG_PY = REPO_ROOT / "config.py"

# Nur die vier UNABHÄNGIGEN Fachbereichs-Mengen in config.py sind gültige Ziele -
# DEPARTMENT_CREATIVE_AGENTS ist eine abgeleitete Vereinigung (DESIGN | CONTENT | {"creative_lead"},
# siehe config.py) und darf nicht direkt erweitert werden, sonst geht die Ergänzung beim
# nächsten Modul-Reload verloren bzw. verändert die falsche Zeile.
DEPARTMENT_SET_NAMES = {
    "planning": "DEPARTMENT_PLANNING_AGENTS",
    "design": "DEPARTMENT_DESIGN_AGENTS",
    "dev": "DEPARTMENT_DEV_AGENTS",
    "content": "DEPARTMENT_CONTENT_AGENTS",
    "qa": "DEPARTMENT_QA_AGENTS",
    "governance": "DEPARTMENT_GOVERNANCE_AGENTS",
}
TIER_MODEL_EXPR = {"lite": "LITE_MODEL", "standard": "STANDARD_MODEL", "heavy": "HEAVY_MODEL"}


def _pascal_case(agent_id: str) -> str:
    return "".join(part.capitalize() for part in agent_id.split("_"))


def render_agent_file(agent_id: str, class_name: str, name: str, description: str, phase: int) -> str:
    """Erzeugt den Inhalt von `agents/<agent_id>_agent.py` - ein lauffähiges Gerüst, dessen
    System-Prompt bewusst TODO-Platzhalter enthält: eine fachlich gute Rollenbeschreibung lässt
    sich nicht sinnvoll generisch generieren, das Gerüst spart nur den Boilerplate-Anteil
    (Klassenstruktur, super().__init__(), Docstring-Form) - siehe eine bestehende Rolle
    ähnlicher Komplexität für einen Stil-Vergleich."""
    return f'''"""
agents/{agent_id}_agent.py – {name}

TODO: kurze Beschreibung der Spezialisierung dieser Rolle (2-5 Stichpunkte), siehe eine
bestehende Agentenklasse ähnlicher Komplexität als Stilvorlage.
"""

from agents.base_agent import BaseAgent


class {class_name}(BaseAgent):
    """
    TODO: ein Satz, wofür dieser Agent zuständig ist. Läuft in Phase {phase}.
    """

    def __init__(self):
        super().__init__(agent_id="{agent_id}", name="{name}")

    @property
    def system_prompt(self) -> str:
        return """TODO: vollständigen System-Prompt ausformulieren.

Rollenbeschreibung (aus dem Scaffold-Aufruf übernommen, ggf. präzisieren):
{description}

TODO: Kernkompetenzen, erwartetes Ausgabeformat und Ton/Sprache (Deutsch, wie die anderen
Rollen dieses Teams) ergänzen."""
'''


def insert_orchestrator_registration(text: str, agent_id: str, class_name: str) -> str:
    """Ergänzt den Import UND den `self._agents`-Eintrag in `agents/orchestrator/__init__.py`.
    Die exakte alphabetische Position des Imports ist hier bewusst NICHT relevant - main()
    lässt `ruff check --fix` danach laufen, das sortiert Imports zuverlässiger als eine
    hier nachgebaute Sortier-Heuristik."""
    import_line = f"from agents.{agent_id}_agent import {class_name}\n"
    if import_line in text:
        raise ValueError(f"Import für '{class_name}' existiert bereits in {ORCHESTRATOR_INIT.name}.")
    # Direkt nach der letzten "from agents.<x>_agent import ..."-Zeile einfügen.
    agent_import_re = re.compile(r"^from agents\.\w+_agent import \w+\n", re.MULTILINE)
    matches = list(agent_import_re.finditer(text))
    if not matches:
        raise ValueError(f"Kein bestehender Agenten-Import in {ORCHESTRATOR_INIT.name} gefunden - Anker fehlt.")
    insert_at = matches[-1].end()
    text = text[:insert_at] + import_line + text[insert_at:]

    dict_entry = f'            "{agent_id}":'.ljust(33) + f"{class_name}(),\n"
    marker = "        self._agents: dict[str, BaseAgent] = {\n"
    marker_pos = text.find(marker)
    if marker_pos == -1:
        raise ValueError(f"self._agents-Dict-Deklaration in {ORCHESTRATOR_INIT.name} nicht gefunden - Anker fehlt.")
    close_pos = text.find("\n        }\n", marker_pos)
    if close_pos == -1:
        raise ValueError(f"Schließende Klammer von self._agents in {ORCHESTRATOR_INIT.name} nicht gefunden.")
    return text[:close_pos] + "\n" + dict_entry.rstrip("\n") + text[close_pos:]


def insert_task_manager_entry(text: str, agent_id: str, name: str, phase: int, description: str) -> str:
    """Ergänzt den Eintrag in `core.task_manager.AVAILABLE_AGENTS`."""
    entry_key = f'    "{agent_id}": {{\n'
    if entry_key in text:
        raise ValueError(f"'{agent_id}' existiert bereits in AVAILABLE_AGENTS ({TASK_MANAGER.name}).")
    entry = (
        f'    "{agent_id}": {{\n'
        f'        "name": "{name}",\n'
        f'        "phase": {phase},\n'
        f'        "description": "{description}",\n'
        f"    }},\n"
    )
    marker = "AVAILABLE_AGENTS = {\n"
    marker_pos = text.find(marker)
    if marker_pos == -1:
        raise ValueError(f"AVAILABLE_AGENTS-Deklaration in {TASK_MANAGER.name} nicht gefunden - Anker fehlt.")
    close_pos = text.find("\n}\n", marker_pos)
    if close_pos == -1:
        raise ValueError(f"Schließende Klammer von AVAILABLE_AGENTS in {TASK_MANAGER.name} nicht gefunden.")
    return text[:close_pos] + "\n" + entry.rstrip("\n") + text[close_pos:]


def insert_config_entries(text: str, agent_id: str, tier: str, department: str) -> str:
    """Ergänzt den Eintrag in `config.AGENT_MODELS` UND fügt die Rolle der gewählten
    `DEPARTMENT_*_AGENTS`-Menge hinzu."""
    model_expr = TIER_MODEL_EXPR[tier]
    env_var = f"{agent_id.upper()}_MODEL"
    model_line = f'    "{agent_id}":'.ljust(25) + f'os.getenv("{env_var}", {model_expr}),\n'
    if f'"{agent_id}":' in text.split("AGENT_MODELS: dict[str, str] = {", 1)[-1].split("\n}", 1)[0]:
        raise ValueError(f"'{agent_id}' existiert bereits in AGENT_MODELS ({CONFIG_PY.name}).")

    marker = "AGENT_MODELS: dict[str, str] = {\n"
    marker_pos = text.find(marker)
    if marker_pos == -1:
        raise ValueError(f"AGENT_MODELS-Deklaration in {CONFIG_PY.name} nicht gefunden - Anker fehlt.")
    close_pos = text.find("\n}\n", marker_pos)
    if close_pos == -1:
        raise ValueError(f"Schließende Klammer von AGENT_MODELS in {CONFIG_PY.name} nicht gefunden.")
    text = text[:close_pos] + "\n" + model_line.rstrip("\n") + text[close_pos:]

    set_name = DEPARTMENT_SET_NAMES[department]
    set_line_re = re.compile(rf"^{set_name} = \{{(.*)\}}$", re.MULTILINE)
    match = set_line_re.search(text)
    if not match:
        raise ValueError(f"{set_name}-Deklaration in {CONFIG_PY.name} nicht gefunden - Anker fehlt.")
    if f'"{agent_id}"' in match.group(1):
        raise ValueError(f"'{agent_id}' ist bereits Teil von {set_name}.")
    new_line = f'{set_name} = {{{match.group(1)}, "{agent_id}"}}'
    return text[: match.start()] + new_line + text[match.end():]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Legt das Gerüst einer neuen Agentenrolle an und registriert sie an allen vier nötigen Stellen.")
    parser.add_argument("agent_id", help="snake_case-ID der neuen Rolle, z.B. 'load_tester'")
    parser.add_argument("--name", required=True, help="Anzeigename, z.B. 'Load-Test-Spezialist'")
    parser.add_argument("--description", required=True, help="Kurzbeschreibung für den Planer-Prompt")
    parser.add_argument("--phase", type=int, required=True, choices=range(1, 7), help="Phase 1-6")
    parser.add_argument("--department", required=True, choices=sorted(DEPARTMENT_SET_NAMES))
    parser.add_argument("--tier", required=True, choices=sorted(TIER_MODEL_EXPR), help="Modell-Komplexitätsstufe")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.agent_id):
        parser.error("agent_id muss snake_case sein (Kleinbuchstaben, Ziffern, Unterstriche).")

    class_name = _pascal_case(args.agent_id) + "Agent"
    agent_file = REPO_ROOT / "agents" / f"{args.agent_id}_agent.py"
    if agent_file.exists():
        parser.error(f"{agent_file} existiert bereits.")

    try:
        orchestrator_text = insert_orchestrator_registration(ORCHESTRATOR_INIT.read_text(encoding="utf-8"), args.agent_id, class_name)
        task_manager_text = insert_task_manager_entry(TASK_MANAGER.read_text(encoding="utf-8"), args.agent_id, args.name, args.phase, args.description)
        config_text = insert_config_entries(CONFIG_PY.read_text(encoding="utf-8"), args.agent_id, args.tier, args.department)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    agent_file.write_text(
        render_agent_file(args.agent_id, class_name, args.name, args.description, args.phase), encoding="utf-8",
    )
    ORCHESTRATOR_INIT.write_text(orchestrator_text, encoding="utf-8")
    TASK_MANAGER.write_text(task_manager_text, encoding="utf-8")
    CONFIG_PY.write_text(config_text, encoding="utf-8")

    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--fix",
         str(agent_file), str(ORCHESTRATOR_INIT), str(TASK_MANAGER), str(CONFIG_PY)],
        cwd=REPO_ROOT, check=False,
    )

    print(f"✅ Rolle '{args.agent_id}' ({class_name}) angelegt und an allen 4 Stellen registriert:")
    print(f"   - {agent_file.relative_to(REPO_ROOT)} (NEU - System-Prompt noch ausformulieren, siehe TODOs)")
    print(f"   - {ORCHESTRATOR_INIT.relative_to(REPO_ROOT)}")
    print(f"   - {TASK_MANAGER.relative_to(REPO_ROOT)}")
    print(f"   - {CONFIG_PY.relative_to(REPO_ROOT)}")
    print("\nNächster Schritt: pytest tests/test_agent_registry_consistency.py")
    return 0


if __name__ == "__main__":
    # Windows-UTF-8-Fix (wie main.py): ohne das crasht print() mit UnicodeEncodeError auf der
    # Standard-Konsolen-Codepage (cp1252), sobald eine der ✅/❌-Statuszeilen unten ausgegeben
    # wird. Bewusst NUR hier (nicht auf Modulebene) - ein Import dieses Moduls für Tests darf
    # sys.stdout/-stderr nicht global umbiegen, das würde pytests eigenes Output-Capturing
    # brechen (real beobachtet: `ValueError: I/O operation on closed file` beim Teardown, sobald
    # ein Test dieses Modul importiert).
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
