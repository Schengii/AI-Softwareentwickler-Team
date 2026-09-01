"""
core/design_system.py – Projekt-Design-System: feste visuelle Präferenzen über Sitzungen
hinweg

Realer Fund (Bestandsaufnahme des eigenen Teams): core/project_constitution.py gibt dem
Nutzer bereits Kontrolle über feste TECH-STACK-Präferenzen (Sprache, Framework, Code-Stil),
die JEDEM künftigen Lauf an einem Projekt mitgegeben werden. Seit der Design-vor-Dev-
Phasenaufteilung (design_lead läuft VOR dev_lead) hat aber ausgerechnet das VISUELLE
Design-System (Farbpalette, Typografie, Spacing-Skala, Komponenten-Namenskonvention, Tonalität
für Copy) kein Pendant: jeder neue Lauf am selben Projekt lässt `ui_ux`/`image_generator`/
`copywriter` diese Entscheidungen praktisch neu erfinden, statt sie konsistent
fortzuschreiben – ein zweiter Lauf am selben Projekt kann so eine andere Primärfarbe oder
Schriftart wählen als der erste, ohne dass die Nutzeranfrage das je erwähnt hätte.

Dieses Modul schließt genau diese Lücke, nach demselben Muster wie project_constitution.py:
eine einfache, von Hand lesbare/editierbare TOML-Datei direkt im Projektverzeichnis (bewusst
NICHT gitignored – echte, wertvolle Projekt-Konfiguration, kein Build-Artefakt), die bei JEDEM
künftigen Lauf als verbindlicher Kontext an alle Agenten mitgegeben wird.
"""

import tomllib
from pathlib import Path

DESIGN_SYSTEM_FILENAME = ".ai-team-design.toml"

# Feld-Name -> Anzeige-Label (Reihenfolge = Anzeige-/Abfrage-Reihenfolge in der CLI).
FIELDS: dict[str, str] = {
    "color_palette": "Farbpalette (Primär-/Sekundär-/Akzentfarben, z. B. Hex-Codes)",
    "typography": "Typografie (Schriftarten für Headlines/Fließtext)",
    "spacing_scale": "Spacing-/Layout-Skala (z. B. 4px-Basis-Raster)",
    "component_naming": "Komponenten-Namenskonvention (z. B. BEM, Atomic Design)",
    "tone_of_voice": "Tonalität für Texte (für copywriter, z. B. 'locker-professionell, Du-Form')",
    "notes": "Weitere verbindliche Design-Hinweise",
}


def _design_system_path(project_dir: str) -> Path:
    return Path(project_dir) / DESIGN_SYSTEM_FILENAME


def read_design_system(project_dir: str) -> dict[str, str]:
    """Gibt die gespeicherten Design-Präferenzen zurück (leeres dict, falls keine Datei
    existiert oder sie beschädigt ist – kein Crash, dasselbe Prinzip wie
    core/project_constitution.py.read_constitution())."""
    path = _design_system_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in FIELDS and str(v).strip()}


def write_design_system(project_dir: str, fields: dict[str, str]) -> None:
    """
    Schreibt die Design-Präferenzen (nur bekannte, nicht-leere Felder – ein leerer Wert
    entfernt das Feld, statt eine leere Zeile zu speichern). I/O-Fehler werden verschluckt
    (rein additiv, darf nie einen sonst erfolgreichen CLI-Befehl zum Scheitern bringen –
    dasselbe Prinzip wie project_constitution.write_constitution()).
    """
    clean = {k: v.strip() for k, v in fields.items() if k in FIELDS and v and v.strip()}
    lines = [
        "# .ai-team-design.toml - Projekt-Design-System: gilt fuer JEDEN kuenftigen Lauf an diesem Projekt.",
        "# Von Hand editierbar, oder ueber /design-system in der CLI.",
        "",
    ]
    for key, value in clean.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key} = "{escaped}"')
    try:
        _design_system_path(project_dir).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def format_design_system_for_agents(project_dir: str) -> str:
    """
    Formatiert die Design-Präferenzen als kompakten, verbindlichen Kontext-Block für die
    Aufgabenbeschreibung der Agenten – leer, wenn kein Design-System existiert (kein
    leerer/unnötiger Abschnitt im Prompt für die Mehrheit der Projekte ohne eines).
    """
    design_system = read_design_system(project_dir)
    if not design_system:
        return ""

    lines = ["## 🎨 Projekt-Design-System (verbindliche visuelle Präferenzen des Nutzers):"]
    for key, label in FIELDS.items():
        if key in design_system:
            lines.append(f"- **{label}:** {design_system[key]}")
    lines.append("Halte dich an dieses Design-System, außer die Aufgabe verlangt explizit etwas anderes.")
    return "\n".join(lines)
