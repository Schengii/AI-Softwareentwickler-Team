"""
core/project_constitution.py – Projekt-Konstitution: feste Tech-Stack-Präferenzen über
Sitzungen hinweg

Realer Fund: project_slug/Architektur/Tech-Stack werden pro Lauf frisch vom Modell geraten –
selbst am selben Projekt kann Lauf 2 eine andere Sprache/Framework wählen als Lauf 1, wenn die
Nutzeranfrage das nicht jedes Mal explizit wiederholt. core/project_status.py gibt dem Team
Kontinuität über die LAUF-HISTORIE; dieses Modul gibt dem NUTZER die Kontrolle über feste
Tech-Stack-Präferenzen (Sprache, Framework, Test-Framework, Code-Stil, Deployment-Ziel), die
JEDEM künftigen Lauf an diesem Projekt als verbindlicher Kontext mitgegeben werden – einmal
festgelegt statt bei jeder Anfrage neu spezifiziert.

Schreibt/liest eine einfache, von Hand lesbare/editierbare TOML-Datei direkt im
Projektverzeichnis (bewusst NICHT gitignored, wie .ai_team_status.json – echte, wertvolle
Projekt-Konfiguration, kein Build-Artefakt). Nutzt stdlib tomllib zum Lesen (Python 3.11+,
ohnehin die Mindestversion dieses Frameworks); zum Schreiben reicht ein minimaler Hand-Writer,
da das Schema aus flachen String-Feldern besteht – keine zusätzliche Abhängigkeit nötig.
"""

import tomllib
from pathlib import Path

CONSTITUTION_FILENAME = ".ai-team.toml"

# Feld-Name -> Anzeige-Label (Reihenfolge = Anzeige-/Abfrage-Reihenfolge in der CLI).
FIELDS: dict[str, str] = {
    "language": "Programmiersprache",
    "framework": "Framework",
    "test_framework": "Test-Framework",
    "code_style": "Code-Stil / Konventionen",
    "deployment_target": "Deployment-Ziel",
    "notes": "Weitere verbindliche Hinweise",
    "max_project_tokens": "Max. Tokens für dieses Projekt insgesamt (0/leer = unbegrenzt)",
}
# max_project_tokens ist eine operative Kennzahl (Grundlage für das harte Budget in
# agents/orchestrator.py), keine inhaltliche Vorgabe für die Agenten - taucht deshalb NICHT im
# per format_constitution_for_agents() injizierten Prompt-Kontext auf (ein Zahlenlimit wäre dort
# nur unnötiger Prompt-Text ohne Wirkung auf die eigentliche Aufgabe).
_OPERATIONAL_FIELDS: frozenset[str] = frozenset({"max_project_tokens"})


def _constitution_path(project_dir: str) -> Path:
    return Path(project_dir) / CONSTITUTION_FILENAME


def read_constitution(project_dir: str) -> dict[str, str]:
    """Gibt die gespeicherten Tech-Stack-Präferenzen zurück (leeres dict, falls keine Datei
    existiert oder sie beschädigt ist – kein Crash, dasselbe Prinzip wie
    core/project_status.py.read_status())."""
    path = _constitution_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in FIELDS and str(v).strip()}


def write_constitution(project_dir: str, fields: dict[str, str]) -> None:
    """
    Schreibt die Tech-Stack-Präferenzen (nur bekannte, nicht-leere Felder – ein leerer Wert
    entfernt das Feld, statt eine leere Zeile zu speichern). I/O-Fehler werden verschluckt
    (rein additiv, darf nie einen sonst erfolgreichen CLI-Befehl zum Scheitern bringen –
    dasselbe Prinzip wie record_run()).
    """
    clean = {k: v.strip() for k, v in fields.items() if k in FIELDS and v and v.strip()}
    lines = [
        "# .ai-team.toml - Projekt-Konstitution: gilt fuer JEDEN kuenftigen Lauf an diesem Projekt.",
        "# Von Hand editierbar, oder ueber /constitution in der CLI.",
        "",
    ]
    for key, value in clean.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key} = "{escaped}"')
    try:
        _constitution_path(project_dir).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def format_constitution_for_agents(project_dir: str) -> str:
    """
    Formatiert die Präferenzen als kompakten, verbindlichen Kontext-Block für die
    Aufgabenbeschreibung der Agenten – leer, wenn keine Konstitution existiert (kein
    leerer/unnötiger Abschnitt im Prompt für die Mehrheit der Projekte ohne eine).
    """
    constitution = read_constitution(project_dir)
    content_fields = {k: v for k, v in constitution.items() if k not in _OPERATIONAL_FIELDS}
    if not content_fields:
        return ""

    lines = ["## 📜 Projekt-Konstitution (verbindliche Tech-Stack-Präferenzen des Nutzers):"]
    for key, label in FIELDS.items():
        if key in content_fields:
            lines.append(f"- **{label}:** {content_fields[key]}")
    lines.append("Halte dich an diese Vorgaben, außer die Aufgabe verlangt explizit etwas anderes.")
    return "\n".join(lines)


def get_max_project_tokens(project_dir: str) -> int:
    """
    Liest `max_project_tokens` aus der Konstitution und gibt es als int zurück (0 = unbegrenzt/
    nicht gesetzt/ungültiger Wert – kein Crash bei einem versehentlich nicht-numerischen Wert,
    dieselbe tolerante Grundhaltung wie read_constitution() selbst). Grundlage für das
    Pro-Projekt-Kostenbudget in agents/orchestrator.py.
    """
    raw = read_constitution(project_dir).get("max_project_tokens", "")
    try:
        return max(0, int(raw))
    except (ValueError, TypeError):
        return 0
