"""
core/verifier/models.py – gemeinsame Datenklassen und Konstanten für alle Verifikations-
Checks (Lint, SAST/Security, Dependency-/License-Audit, Coverage, Runtime/Smoke, Lasttest).

Diese Datei enthält bewusst keine Prüf-Logik selbst, nur die Ergebnistypen und die kleinen,
von mehreren Checks geteilten Konstanten/Hilfsfunktionen – siehe core/verifier/__init__.py
für die Zusammensetzung der eigentlichen ProjectVerifier-Klasse aus den einzelnen
Check-Mixins (core/verifier/environment.py, testrunner.py, security.py, lint.py,
coverage.py, runtime.py).
"""

import re
import sys
from dataclasses import dataclass, field

VENV_DIRNAME = ".ai_team_venv"

# Verzeichnisse, die weder als Python- noch als Node-Testquelle zählen – Build-/Umgebungs-
# Artefakte, keine vom Team geschriebenen Projektdateien.
_IGNORED_DIRS = {VENV_DIRNAME, ".venv", "venv", "__pycache__", "node_modules", ".git"}

# Best-effort-Erkennung fehlgeschlagener npm-Tests: Jest/Vitest melden fehlgeschlagene
# Testdateien als "FAIL <pfad>" bzw. mit "✕"/"×" vor dem Testnamen. Da es kein einheitliches
# Node-Test-Ausgabeformat gibt (anders als Python mit pytest/unittest), ist das bewusst ein
# Best-Effort wie bei allen anderen nicht strukturiert geparsten Fehlschlägen (siehe
# _parse_python_failures unten) – kein Anspruch, jedes Framework exakt zu parsen.
_NODE_FAIL_FILE_PATTERN = re.compile(r"^(?:FAIL|✕|×)\s+(\S+\.(?:js|jsx|ts|tsx))", re.MULTILINE)
_NODE_STACK_FILE_PATTERN = re.compile(r"\(([^():\n]+\.(?:js|jsx|ts|tsx)):\d+:\d+\)")

# Realer Fund (Pong-Projekt): ein Jest-"Cannot use import statement outside a module"-Fehler
# wurde bisher ausschließlich der TESTDATEI zugeschrieben (sie steht im "FAIL <datei>"-Header)
# und landete deshalb beim tester-Agenten im Fix-Loop - die eigentliche Ursache liegt aber
# fast immer in der Node-Projekt-KONFIGURATION (package.json ohne "type":"module", fehlende
# Jest-Transform/Babel-Config), nicht in der Testlogik selbst. Erkennt die verbreitetsten
# Signaturen genau dieser Fehlerklasse, siehe _parse_node_failures().
_NODE_ENV_ERROR_PATTERN = re.compile(
    r"Cannot use import statement outside a module"
    r"|Jest encountered an unexpected token"
    r"|Cannot find module '[^']+' from"
    r"|is not defined by \"exports\"",
    re.IGNORECASE,
)

# tsc hat kein natives JSON-Format – `--pretty false` liefert stattdessen dieses stabile,
# grep-bare Zeilenformat: "pfad(zeile,spalte): error TSxxxx: nachricht".
_TSC_ERROR_PATTERN = re.compile(r"^(.+?)\((\d+),(\d+)\): (error|warning) (TS\d+): (.+)$", re.MULTILINE)

# ESLint-Konfigurationsdateien, deren Vorhandensein signalisiert, dass das Projekt ESLint
# selbst bewusst eingerichtet hat – nur DANN wird gelintet, um keine ungefragte Meinung
# über den Code-Stil eines Projekts durchzusetzen, das sich nie für ESLint entschieden hat.
_ESLINT_CONFIG_NAMES = (
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml",
)


@dataclass
class TestFailure:
    """Ein einzelner, aus der echten Testausgabe geparster Fehlschlag."""
    test_id: str
    message: str
    files: list[str] = field(default_factory=list)  # Relative Projektpfade, die im Traceback auftauchen


@dataclass
class VerificationReport:
    """Ergebnis eines echten Verifikationslaufs (kein Keyword-Raten)."""
    ran: bool
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    failures: list[TestFailure] = field(default_factory=list)
    reason_skipped: str = ""


@dataclass
class DockerBuildReport:
    """
    Ergebnis eines echten `docker build`-Versuchs – Teil der "echtes Deployment"-Ambition:
    ein generiertes Dockerfile, das nie tatsächlich baut, ist praktisch wertlos für den
    Anspruch, ein Projekt bis zum Ausrollen zu bringen. Wie bei fehlenden Tests (siehe
    VerificationReport.reason_skipped) gilt: kein Dockerfile bzw. keine lokale Docker-
    Installation ist KEIN Fehler, nur nicht prüfbar (attempted=False).
    """
    attempted: bool
    success: bool
    output: str
    reason_skipped: str = ""


@dataclass
class DependencyVulnerability:
    """Eine einzelne, aus einem echten pip-audit-/npm-audit-Scan geparste Schwachstelle."""
    package: str
    version: str
    vulnerability_id: str
    description: str
    severity: str = ""
    # Nur von pip-audit geliefert (aufsteigend sortierte Liste kompatibler sicherer Versionen
    # direkt aus der Advisory-Datenbank) - Grundlage für core/dependency_updater.py, das
    # verwundbare Pakete automatisch auf die erste (niedrigste sichere) Version anhebt. npm
    # audit liefert keine vergleichbar einfache Angabe, bleibt daher leer.
    fix_versions: list[str] = field(default_factory=list)


@dataclass
class DependencyAuditReport:
    """
    Ergebnis eines echten Dependency-Vulnerability-Scans (`pip-audit` für Python,
    `npm audit` für Node) – ersetzt die bisherige rein LLM-basierte Einschätzung des
    security-Agenten, der Abhängigkeiten nur "plausibel" bewerten konnte, durch einen
    echten Abgleich gegen eine öffentliche CVE-/Advisory-Datenbank.

    Wie bei DockerBuildReport gilt: eine fehlende Abhängigkeitsdatei, ein fehlendes
    Scan-Tool ODER ein technischer Fehlschlag des Scans selbst (z. B. keine
    Netzwerkverbindung zur Advisory-Datenbank) sind KEIN Fehler, nur nicht prüfbar
    (attempted=False) – und werden NIEMALS fälschlich als "keine Schwachstellen gefunden"
    gemeldet. Das wäre ein gefährlicher falscher Sicherheitsanspruch: ein technischer
    Fehlschlag des Scans ist etwas anderes als ein sauberes Scan-Ergebnis.
    """
    attempted: bool
    vulnerable: bool
    tool: str
    vulnerabilities: list[DependencyVulnerability] = field(default_factory=list)
    reason_skipped: str = ""


@dataclass
class SastFinding:
    """Ein einzelnes, aus einer echten `bandit`-Ausgabe geparstes Sicherheits-Fundstück."""
    file_path: str
    line_number: int
    message: str
    rule: str = ""
    severity: str = ""  # bandit issue_severity: LOW/MEDIUM/HIGH


@dataclass
class SastReport:
    """
    Ergebnis eines echten Static-Application-Security-Testing-Laufs (`bandit` für Python) –
    ersetzt die bisherige rein LLM-basierte Einschätzung des security-Agenten (Freitext-
    Vermutungen ohne konkrete Datei/Zeile) durch einen echten, statischen Scan gegen bekannte
    Schwachstellenmuster im eigenen Code (hartcodierte Secrets, unsichere Deserialisierung,
    SQL-Injection-Vektoren, unsichere Zufallszahlen/Hashes, `eval`/`exec`, …) – dasselbe
    Prinzip wie DependencyAuditReport für Abhängigkeits-CVEs, nur für selbst geschriebenen
    Code statt Fremdpakete.

    Aktuell nur Python (bandit, braucht keine Projekt-Konfiguration – wie ruff bei
    LintReport). JS/TS/Go/Rust-Unterstützung (z. B. via semgrep) ist eine naheliegende
    spätere Erweiterung, analog dazu, wie auch der Dependency-Audit schrittweise über
    mehrere Runden auf Node/Rust/Go ausgeweitet wurde – kein Anspruch auf Vollständigkeit
    in dieser ersten Stufe.

    Wie bei DependencyAuditReport gilt: fehlendes Tool oder ein technischer Fehlschlag des
    Scans selbst sind KEIN Fehler, nur nicht prüfbar (attempted=False) – und werden NIEMALS
    fälschlich als "keine Funde" gemeldet.
    """
    attempted: bool
    vulnerable: bool
    tool: str
    findings: list[SastFinding] = field(default_factory=list)
    reason_skipped: str = ""


def _csv_float(row: dict, key: str) -> float | None:
    """Liest ein Feld aus einer per csv.DictReader gelesenen Zeile als float - None statt
    Crash bei fehlendem/leerem/nicht-numerischem Wert (z. B. eine Locust-Version ohne diese
    Spalte)."""
    raw = row.get(key)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


_COPYLEFT_LICENSE_MARKERS = ("GPL", "MPL", "CDDL", "EUPL", "SSPL")


def _is_copyleft_license(license_str: str) -> bool:
    """
    Einfache Namens-Heuristik (bekannte Copyleft-Lizenz-Bezeichner als Teilstring, z. B.
    "GNU General Public License v3 (GPLv3)" oder "LGPL") - kein Anspruch auf juristische
    Vollständigkeit (z. B. Dual-Lizenzierung wird nicht aufgelöst), aber ein echter erster
    Filter statt reinem Raten. "GPL" fängt bewusst auch AGPL/LGPL als Teilstring mit ab.
    """
    upper = (license_str or "").upper()
    return any(marker in upper for marker in _COPYLEFT_LICENSE_MARKERS)


@dataclass
class LicenseFinding:
    """Eine einzelne, aus einem echten Lizenz-Scan geparste Abhängigkeit mit ihrer Lizenz."""
    package: str
    version: str
    license: str
    copyleft: bool = False


@dataclass
class LicenseAuditReport:
    """
    Ergebnis eines echten Open-Source-Lizenz-Scans (`pip-licenses` für Python, liest die
    Metadaten der TATSÄCHLICH installierten Pakete) – ersetzt die bisherige rein
    LLM-basierte Einschätzung des compliance-Agenten (eine geratene "MIT/AGPL 🔴"-Tabelle im
    Report) durch eine echte, aus den installierten Paketen gelesene Lizenzliste. Rechtlich
    riskant: eine geratene Lizenzangabe kann bei einem echten Copyleft-Paket (GPL/AGPL) zu
    falscher Sicherheit führen, ähnlich wie eine geratene CVE-Einschätzung ohne echten
    Dependency-Audit.

    Aktuell nur Python (pip-licenses). Node-Unterstützung (z. B. via `license-checker`) ist
    eine naheliegende spätere Erweiterung, analog dazu, wie auch der Dependency-Audit
    schrittweise über mehrere Runden auf Node/Rust/Go ausgeweitet wurde.

    Wie bei DependencyAuditReport gilt: fehlendes Tool oder ein technischer Fehlschlag des
    Scans selbst sind KEIN Fehler, nur nicht prüfbar (attempted=False) – und werden NIEMALS
    fälschlich als "keine Copyleft-Risiken" gemeldet.
    """
    attempted: bool
    has_copyleft_risk: bool
    tool: str
    findings: list[LicenseFinding] = field(default_factory=list)
    reason_skipped: str = ""


@dataclass
class LintIssue:
    """Ein einzelnes, aus einer echten ruff-/ESLint-/tsc-Ausgabe geparstes Fundstück."""
    file_path: str
    line_number: int
    message: str
    rule: str = ""


@dataclass
class LintReport:
    """
    Ergebnis eines echten Lint-/Type-Check-Laufs (ruff für Python; ESLint/tsc für Node) –
    ersetzt keine LLM-Einschätzung, sondern liefert erstmals überhaupt eine automatische
    Stil-/Fehlerprüfung für generierten Code (ruff.toml lief bisher NUR gegen den
    Framework-Code selbst, workspace/ dort bewusst ausgeschlossen).

    Python wird IMMER geprüft, wenn .py-Dateien existieren und ruff verfügbar ist – ruff
    braucht keine Projekt-Konfiguration. ESLint/tsc laufen dagegen NUR, wenn das Projekt
    sie selbst bereits als Dev-Abhängigkeit UND Konfiguration mitbringt (siehe
    _ESLINT_CONFIG_NAMES) – keine ungefragte Meinungsänderung an einem Projekt, das sich
    nie für diese Tools entschieden hat.

    Wie bei DockerBuildReport/DependencyAuditReport gilt: fehlendes Tool oder ein
    technischer Fehlschlag des Lint-Laufs selbst sind KEIN Fehler, nur nicht prüfbar
    (attempted=False) – und werden NIEMALS fälschlich als "keine Probleme" gemeldet.
    """
    attempted: bool
    passed: bool
    tool: str
    issues: list[LintIssue] = field(default_factory=list)
    reason_skipped: str = ""


@dataclass
class CoverageReport:
    """
    Ergebnis einer echten Testabdeckungs-Messung (`pytest-cov`) – wie bei DockerBuildReport/
    DependencyAuditReport/LintReport gilt: fehlendes `pytest-cov` im Projekt ist KEIN Fehler,
    nur nicht prüfbar (attempted=False). Das Framework installiert `pytest-cov` NICHT selbst
    nachträglich in die Projekt-venv – dieselbe Zurückhaltung wie bei ESLint/tsc (siehe
    LintReport): kein ungefragter Eingriff in ein Projekt, das sich nie für dieses Tool
    entschieden hat. `agents/tester_agent.py` nimmt `pytest-cov` inzwischen selbst in neu
    generierte `requirements.txt` auf, damit die Messung im Alltagsfall überhaupt greift.
    """
    attempted: bool
    percent: float = 0.0
    reason_skipped: str = ""


@dataclass
class RuntimeSmokeReport:
    """
    Ergebnis eines echten Runtime-Smoke-Tests (App kurz im Subprozess starten & prüfen, ob
    sie fehlerfrei hochfährt und ggf. auf HTTP-Anfragen antwortet).
    """
    attempted: bool
    passed: bool = False
    entrypoint: str = ""
    app_type: str = ""  # "http_api", "cli_script", "node_server"
    status_code: int | None = None
    output: str = ""
    reason_skipped: str = ""


@dataclass
class PerfCheckReport:
    """
    Ergebnis eines echten, kurzen Lastentest-Laufs (k6/locust) gegen die generierte, tatsächlich
    gestartete App – ersetzt die bisherige Situation, in der der performance-Agent vollständige
    Lastentest-Skripte schreibt, die aber NIE ausgeführt werden (anders als z. B. run_tests()).

    Bewusst KEIN vollständiger Lasttest (der würde Minuten dauern und echte Ressourcen binden),
    sondern ein kurzer SMOKE-Lasttest mit wenigen virtuellen Nutzern über wenige Sekunden - genug,
    um zu prüfen, ob die App unter minimaler gleichzeitiger Last überhaupt fehlerfrei antwortet,
    kein Performance-Benchmark und keine Kapazitätsaussage.

    Wie bei allen anderen Checks gilt: fehlendes Skript/Tool oder ein technischer Fehlschlag
    (z. B. die App startet gar nicht) sind KEIN Fehler, nur nicht prüfbar (attempted=False) –
    und werden NIEMALS fälschlich als "bestanden" gemeldet.
    """
    attempted: bool
    passed: bool = False
    tool: str = ""
    script: str = ""
    total_requests: int = 0
    failed_requests: int = 0
    p95_ms: float | None = None
    output: str = ""
    reason_skipped: str = ""


# Verzeichnis, unter dem der performance-Agent Lastentest-Skripte ablegt (siehe
# agents/performance_agent.py) - dieselbe Konvention wie specs/openapi.yaml beim
# api_integration-Agenten: ein fester, dokumentierter Pfad, an dem check_load_test() gezielt
# suchen kann, statt beliebige Dateinamen im ganzen Projekt erraten zu müssen.
LOAD_TEST_DIRNAME = "tests/load"

# Realer Fund (Bestandsaufnahme cloudvault-Projekt): "Tests grün" wurde bisher mit "Feature
# fertig" verwechselt - ein Endpunkt mit dem Kommentar "Hier würde die AES-256-GCM
# Verschlüsselung ... erfolgen" bestand die Testsuite trotzdem, weil die Tests denselben Stub
# prüften, den der Code tatsächlich liefert. Diese Marker fangen die verbreitetsten Deutsch-/
# Englisch-Formulierungen für "hier fehlt die echte Implementierung" ab - bewusst eine Text-
# Heuristik wie _CRITICAL_RE (core/review_gate.py), kein Anspruch auf Vollständigkeit. Ein
# einzelner Treffer ist kein Beweis für unfertigen Code (z.B. ein legitimer TODO-Kommentar für
# spätere Optimierung) - deshalb bleibt check_completeness() informativ genug dokumentiert,
# aber blockiert verification_ok wie ein echter Testfehler (siehe CompletenessReport).
_STUB_MARKER_RE = re.compile(
    r"hier\s+w[üu]rde\b"
    r"|hier\s+w[äa]re\b"
    r"|\(simuliert\)"
    r"|wird\s+simuliert\b"
    r"|not\s+implemented"
    r"|notimplementederror"
    r"|todo\s*:?\s*implement"
    r"|for\s+demo(nstration)?\s+purposes"
    r"|placeholder\s+(implementation|for|value)"
    r"|in\s+(einer\s+)?echten\s+implementierung\s+w[üu]rde",
    re.IGNORECASE,
)

# Dateiendungen, die check_completeness() nach Stub-Markern durchsucht - dieselben Sprachen,
# die auch der echte Lint-/SAST-Check abdeckt (Python/JS/TS immer relevant, Go/Rust/Ruby/Java
# als verbreitete Backend-Sprachen des Frameworks, siehe agents/backend_agent.py).
_STUB_SCAN_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".java"}

# README-Installationsbefehle, die typischerweise auf eine konkrete Datei verweisen, die dann
# auch wirklich existieren muss (z.B. "pip install -r requirements.txt", "psql -f schema.sql")
# - real beobachtet: cloudvault-Projekt verwies auf eine requirements.txt, die nie generiert
# wurde. Erfasst den Dateinamen als Gruppe 1.
_README_FILE_REF_RE = re.compile(
    r"(?:-r|--requirement|-f|--file)\s+([./\w-]+\.(?:txt|sql|ya?ml|json|env))",
    re.IGNORECASE,
)

# Zweiter realer Fund im selben cloudvault-Projekt, den die reine Stub-Kommentar-Suche NICHT
# erfasst hätte: `list_files()` gab hart `return []` zurück und `get_tags()` eine hartcodierte
# Konstantenliste - kein "Hier würde..."-Kommentar, trotzdem keine echte Persistenz/Anbindung.
# Erkennt Python-Routen-Handler (FastAPI/Flask-Dekoratoren für schreibende Verben, wo eine
# fehlende Anbindung am schwersten wiegt - GET wird bewusst ausgenommen, um Health-/Status-
# Endpunkte ohne I/O nicht fälschlich zu melden) und prüft den Funktionskörper auf mindestens
# einen erkennbaren I/O-Aufruf (DB/Storage/HTTP-Client).
_PY_WRITE_ROUTE_DECORATOR_RE = re.compile(
    r"@(?:app|router|blueprint|bp|api)\.(?:post|put|patch|delete)\(",
    re.IGNORECASE,
)
_PY_ROUTE_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
_IO_CALL_MARKERS = (
    "session", "db.", "db_", "cursor", "execute(", "query(", ".save(", "insert(",
    "update(", "delete(", "open(", "s3", "boto3", "redis", "requests.", "httpx.",
    "aiofiles", "read_text(", "write_text(", "read_bytes(", "write_bytes(",
    ".find(", ".find_one(", "select(", "commit(", "flush(", "orm", "prisma",
    "os.remove", "shutil.", "upload_fileobj",
)
# Zweite, eigene Markergruppe für die verbreitete In-Memory-Store-Persistenz kleiner Demo-Apps
# (z.B. `notes_db[note_id] = note`, `monitor.checks.pop(id, None)`, `monitor.add_check(check)`)
# - real beobachtet als Falsch-Positiv-Quelle beim ersten Entwurf dieses Checks: ein `dict` als
# Store ist keine Stub-Implementierung, nur kein DB-/Storage-Framework. Separates Muster statt
# Teil von _IO_CALL_MARKERS, weil es strukturell (Subscript-Zuweisung/Methodenaufruf) statt rein
# textuell erkannt wird.
_IO_MUTATION_RE = re.compile(
    r"\w+\[[^\]\n]+\]\s*="  # z.B. notes_db[note_id] = ...
    r"|\bdel\s+\w+\["  # z.B. del notes_db[note_id]
    r"|\.pop\("
    r"|\.add\w*\("
    r"|\.create\w*\("
    r"|\.save\w*\("
    r"|\.store\w*\("
    r"|\.append\("
    r"|\.update\w*\("
    r"|\.remove\("
    r"|\.insert\w*\(",
)
# Endpunktnamen, bei denen eine fehlende I/O-Anbindung erwartbar/legitim ist (z.B. ein reiner
# Logout, der nur ein Cookie löscht) - bewusst kurz gehalten, kein Anspruch auf Vollständigkeit.
_ROUTE_IO_EXEMPT_NAME_RE = re.compile(r"health|ping|version|logout|status", re.IGNORECASE)

# Dritter realer Fund: `src/components/Dashboard.js` zeigte hartcodierte Fake-Werte
# ("1.2 GB", "42 Dateien") statt Daten über einen API-Aufruf zu laden - eine React-Komponente,
# deren Name auf Datenanzeige hindeutet (Dashboard/List/Table/...), aber weder Props entgegen-
# nimmt noch selbst einen API-Aufruf macht, zeigt fast immer nur Platzhalterdaten.
_COMPONENT_FILENAME_RE = re.compile(r"(?:Dashboard|List|Table|Overview|Panel|Widget)\.(?:jsx?|tsx?)$")
_JSX_RETURN_RE = re.compile(r"return\s*\(")
_API_CALL_MARKER_RE = re.compile(
    r"(?i:fetch\(|axios\.|useeffect|\.get\(|\.post\(|usequery|useswr|graphql|usecontext)"
    # Eigener React-Hook (Konvention: "use" + Großbuchstabe, z.B. `useTaskWebSocket(...)`) -
    # kapselt Datenanbindung (WebSocket/REST/Redux/...) fast immer selbst, auch ohne dass die
    # Komponente die darunterliegenden Primitiven (fetch/axios/useEffect) direkt aufruft. Real
    # beobachtet als Falsch-Positiv-Quelle beim ersten Entwurf: `useTaskWebSocket(...)`. Bewusst
    # GROSS-/Kleinschreibungs-sensitiv (anders als die übrigen Marker oben), sonst würde z.B.
    # `user(...)` fälschlich als Hook-Aufruf zählen.
    r"|\buse[A-Z]\w*\(",
)
_COMPONENT_TAKES_PROPS_RE = re.compile(r"\(\s*\{|\(\s*props\b")

# Vierter realer Fund: cloudvault importierte `fastapi`/`pydantic` (Drittanbieter-Pakete),
# lieferte aber nie eine requirements.txt - der bisherige README-Referenz-Check erfasst das nur,
# wenn das README diese Datei überhaupt erwähnt. Nutzt sys.stdlib_module_names (Python 3.10+)
# statt einer gepflegten Liste, um Standardbibliotheks-Importe von echten Drittanbieter-Paketen
# zu unterscheiden.
_STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
_MANIFEST_FILENAMES = ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "poetry.lock")
_PY_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", re.MULTILINE)


@dataclass
class CompletenessIssue:
    """Ein einzelner Stub-/Platzhalter-Fund oder ein fehlender, in README referenzierter Pfad."""
    file_path: str
    line_number: int = 0
    message: str = ""


@dataclass
class CompletenessReport:
    """
    Ergebnis eines Vollständigkeits-Checks: durchsucht generierten Code nach Platzhalter-/
    Stub-Markern (z.B. "Hier würde die Verschlüsselung erfolgen") und prüft, ob im README per
    Installationsbefehl referenzierte Dateien (requirements.txt, schema.sql, ...) tatsächlich
    existieren. Anders als Lint/SAST rein informativ zu behandeln wäre hier falsch: ein
    Endpunkt, der nur einen Kommentar statt echter Verschlüsselung liefert, ist keine
    Stil-Frage, sondern eine nicht erfüllte fachliche Anforderung - deshalb blockiert ein
    Fund hier verification_ok wie ein echter Testfehler (siehe agents/orchestrator/
    verification.py._run_verification_loop()).
    """
    attempted: bool
    passed: bool = True
    issues: list[CompletenessIssue] = field(default_factory=list)
    reason_skipped: str = ""
