"""
interface/cli/_shared.py – Gemeinsame, unveraenderliche Bausteine der CLI-Mixins (P6-5).

`console` ist EINE gemeinsame Instanz, die alle Mixin-Dateien importieren - Tests patchen
Methoden wie `interface.cli.console.print`/`.input`, was ein Attribut auf diesem GETEILTEN
Objekt ersetzt und deshalb unabhaengig vom jeweiligen Importort wirkt (siehe Modul-Docstring
von scripts/_assemble_cli.py fuer den Unterschied zu einfachen Werte-Patches).
"""

import re
import sys
import time

from rich.console import Console

console = Console()

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║        🤖  KI-Softwareentwickler-Team (v4.3)  🤖            ║
║        ─────────────────────────────────────                 ║
║  Dein 33-köpfiges autonomes KI-Entwickler-Team               ║
║  6 Fachbereiche • RAG • Sandbox • MCP & Web-Dashboard        ║
╚══════════════════════════════════════════════════════════════╝
"""

# Prioritaet eines Backlog-Tickets (core/backlog_store.py.Ticket.priority) - dieselbe
# 1=hoch/2=mittel/3=niedrig-Konvention wie core/message_bus.py.AgentTask.priority.
_PRIORITY_LABELS: dict[str, int] = {"1": 1, "hoch": 1, "2": 2, "mittel": 2, "3": 3, "niedrig": 3}
_PRIORITY_ICONS: dict[int, str] = {1: "🔴 hoch", 2: "🟡 mittel", 3: "🟢 niedrig"}

# ── Mehrzeilige Eingabe (siehe CLIStartupMixin._read_user_input) ───────────────────────────
_BLOCK_DELIMITER = '"""'
_CONTINUATION_SUFFIXES: tuple[str, ...] = ("\\", " /")
# Zeitfenster, in dem nach einer gelesenen Zeile weitere, bereits eingefuegte Zeilen im
# Konsolenpuffer auftauchen - ein Mensch tippt nie so schnell, ein Paste liefert sofort nach.
_PASTE_SETTLE_SECONDS = 0.05
_FRAGMENT_MAX_CHARS = 80
_FRAGMENT_HEADING_RE = re.compile(r"^\s*(#{1,6}\s|[-*_=]{3,}\s*$)")


def _pending_console_input() -> bool:
    """True, wenn im Eingabepuffer bereits weitere Zeilen warten (typisch fuer einen Paste).

    Nur fuer ein echtes Terminal - bei umgeleitetem stdin (Tests, Pipes) immer False, damit
    dort weder gewartet noch blockiert wird."""
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
        time.sleep(_PASTE_SETTLE_SECONDS)
        if sys.platform == "win32":
            import msvcrt

            return bool(msvcrt.kbhit())
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(ready)
    except (OSError, ValueError, ImportError):
        return False


def _looks_like_fragment(text: str) -> bool:
    """Erkennt Eingaben, die offensichtlich nur der Kopf einer laengeren Anforderung sind:
    eine kurze Zeile, die auf „:“ endet, eine Markdown-Ueberschrift, eine Trennlinie oder ein
    Aufzaehlungs-Kopf („2. Sicherheit & Governance:“). Befehle (`/…`) sind nie Fragmente."""
    stripped = text.strip()
    if not stripped or stripped.startswith("/") or "\n" in stripped:
        return False
    if len(stripped) > _FRAGMENT_MAX_CHARS:
        return False
    return stripped.endswith(":") or bool(_FRAGMENT_HEADING_RE.match(stripped))


HELP_TEXT = """
**Verfügbare Befehle:**

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/tokens` | Zeigt den aktuellen Tokenverbrauch und verbleibende Kontingente an |
| `/modelle` | Prüft erneut, welche KI-Modelle gerade wirklich erreichbar sind, inkl. Ampel-Einschätzung, ob sich ein Lauf gerade lohnt (läuft automatisch schon einmal beim Sitzungsstart) |
| `/rag <begriff>` | Führt eine semantische Code-Recherche im geladenen Projekt durch |
| `/team` | Zeigt alle 6 Fachbereiche, Teamleiter und 33 Spezialisten an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/delete-project <name>` | Löscht ein Projekt unwiderruflich aus dem Workspace (mit Bestätigung) |
| `/audit-projekt [projekt]` | Lässt den Projekt-Hygiene-Agenten das Framework (oder ein Projekt) wirklich durchsehen; Löschungen nur nach Bestätigung |
| `/prune-worktrees` | Räumt verwaiste, vom KI-Team angelegte Git-Isolations-Worktrees auf (gemergt oder seit 7+ Tagen inaktiv) |
| `/learnings` | Zeigt alle von den Agenten gelernten Regeln (persistentes Gedächtnis) mit Nummer je Agent an |
| `/lessons [link oder <signatur> <status>]` | Team-Lektionen mit Lebenszyklus (offen → umgesetzt → verifiziert → archiviert) |
| `/optimize` | Zeigt datenbasierte Selbstoptimierungs-Vorschläge über alle bisherigen Läufe hinweg (Modellzuweisung, auffällig niedrige Erfolgsquoten, wiederkehrende Lektionen-Kategorien) – rein informativ, keine automatische Änderung |
| `/apply-tuning <agent_id>` | Übernimmt GEZIELT genau einen der bei `/optimize` angezeigten Modell-Vorschläge für einen einzelnen Agenten – unabhängig von `ENABLE_AUTO_MODEL_TUNING` |
| `/delete-learning <agent> <nr>` | Entfernt eine einzelne, falsche/überholte gelernte Regel (mit Bestätigung) |
| `/constitution [projekt]` | Zeigt/bearbeitet feste Tech-Stack-Präferenzen (Sprache, Framework, Code-Stil, …) für ein Projekt – gilt für jeden künftigen Lauf daran |
| `/design-system [projekt]` | Zeigt/bearbeitet feste visuelle Präferenzen (Farbpalette, Typografie, Spacing-Skala, Tonalität, …) für ein Projekt – gilt für jeden künftigen Lauf daran |
| `/backlog` | Zeigt das Kanban-Board (Todo/In Bearbeitung/Review/Blockiert/Fertig) über CLI, Dashboard UND autonome Issue-Läufe hinweg |
| `/team-health` | Projektübergreifender Health-Rollup über alle Projekte in `workspace/`: Status, seit wann rot, erkannte gemeinsame Fehlermuster |
| `/propose-roadmap <projekt>` | Lässt den product_owner-Agenten read-only 3-5 sinnvolle nächste Schritte für ein bestehendes Projekt vorschlagen – landet als niedrig priorisierte Tickets im Backlog, NICHT automatisch umgesetzt |
| `/backlog-add [priorität] <titel>` | Legt manuell ein priorisiertes, noch nicht begonnenes Ticket im Status "todo" an (Priorität: 1/hoch, 2/mittel, 3/niedrig) |
| `/adr [projekt]` | Zeigt die dokumentierten Architecture Decision Records (Begründungen echter Architektur-Entscheidungen) eines Projekts |
| `/deploy [projekt]` | Deployt ein Projekt lokal per Docker (Compose bevorzugt, sonst Dockerfile) – mit Vorschau & Bestätigung |
| `/deploy-stop [projekt]` | Fährt ein per `/deploy` gestartetes Deployment wieder herunter |
| `/deploy-cloud <fly/vercel/render/railway> [projekt] [--real]` | Deployt in die Cloud (echte Preview-URL) – ohne `--real` nur Dry-Run/Manifeste |
| `/push` | Führt manuell einen Git-Commit & Push aus |
| `/release` | Erstellt einen echten SemVer-Tag + GitHub-Release des FRAMEWORKS selbst aus den Commits seit dem letzten Release (mit Vorschau & Bestätigung) |
| `/rollback <PR-Nummer>` | Revertiert einen bereits gemergten PR über einen echten Revert-Pull-Request (mit Vorschau & Bestätigung) |
| `/protect-branch [branch]` | Aktiviert echte GitHub-Branch-Protection (Pflicht-Reviews, kein Force-Push) für den Hauptbranch – mit Vorschau & Bestätigung |
| `/state [projekt]` | Zeigt den aktuellen State-Checkpoint (PROJECT_STATE.md) und nächste Schritte für ein Projekt an |
| `/goal [max] <ziel>` | Startet den autonomen Ziel-Loop: arbeitet selbstständig in Feedback-Schleifen weiter, bis das Projektziel erreicht und verifiziert ist |
| `/sync-obsidian` | Synchronisiert wichtige Projektdateien (.env, README.md, Zwischenstand etc.) nach Obsidian als Claude-Gedächtnis |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt diese Hilfe an |
| `/beenden` | Beendet das Programm |

**So startest du ein neues Projekt:**
Schreibe einfach deine Anforderung in den Chat (z. B. *"Erstelle eine Todo-Webapp mit FastAPI & SQLite"*).

**So entwickelst du ein bestehendes/externes Projekt weiter:**
1. Lade das Projekt mit `/load C:\\MeinProjekt` oder `/load mein-projekt`
2. Gib dem Team deine Anweisung (z. B. *"Füge Authentifizierung hinzu und refaktoriere die Datenbank"*).
"""
