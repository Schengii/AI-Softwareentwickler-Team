"""
core/verifier/models.py – gemeinsame Datenklassen und Konstanten für alle Verifikations-
Checks (Lint, SAST/Security, Dependency-/License-Audit, Coverage, Runtime/Smoke, Lasttest).

Diese Datei enthält bewusst keine Prüf-Logik selbst, nur die Ergebnistypen und die kleinen,
von mehreren Checks geteilten Konstanten/Hilfsfunktionen – siehe core/verifier/__init__.py
für die Zusammensetzung der eigentlichen ProjectVerifier-Klasse aus den einzelnen
Check-Mixins (core/verifier/environment.py, testrunner.py, security.py, lint.py,
coverage.py, runtime.py).
"""

import ast
import builtins
import re
import sys
from dataclasses import dataclass, field

from core.known_pitfalls import IMPORT_TO_PACKAGE, normalize_package_name

VENV_DIRNAME = ".ai_team_venv"

# Verzeichnisse, die weder als Python- noch als Node-Testquelle zählen – Build-/Umgebungs-
# Artefakte, keine vom Team geschriebenen Projektdateien.
_IGNORED_DIRS = {VENV_DIRNAME, ".venv", "venv", "__pycache__", "node_modules", ".git"}


def _is_get_event_loop_call(node: ast.AST) -> bool:
    """True für `asyncio.get_event_loop(...)` bzw. `get_event_loop(...)` (nach `from asyncio
    import get_event_loop`)."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr == "get_event_loop" and isinstance(f.value, ast.Name) and f.value.id == "asyncio"
    return isinstance(f, ast.Name) and f.id == "get_event_loop"


def find_toplevel_event_loop_calls(source: str) -> list[int]:
    """Zeilennummern von `asyncio.get_event_loop()`-Aufrufen AUSSERHALB einer `async def`-Funktion
    (Modulebene, synchrones `__init__`, jede andere synchrone Funktion) – dort existiert beim
    Import durch pytest noch kein laufender Event-Loop, der Aufruf wirft sofort
    `RuntimeError: There is no current event loop in thread 'MainThread'`. Geteilt zwischen
    core/failure_triage.py (Laufzeit-Triage eines bereits aufgetretenen Fehlers) und
    core/verifier/completeness.py._scan_for_toplevel_event_loop() (statischer Vorab-Check, bevor
    pytest daran scheitert). Ein leeres Ergebnis heißt: keine Fundstelle ODER die Datei ist kein
    gültiges Python (Syntaxfehler werden an anderer Stelle behandelt)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    lines: list[int] = []
    func_stack: list[ast.AST] = []

    class _Visitor(ast.NodeVisitor):
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            func_stack.append(node)
            self.generic_visit(node)
            func_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            func_stack.append(node)
            self.generic_visit(node)
            func_stack.pop()

        def visit_Lambda(self, node: ast.Lambda) -> None:
            func_stack.append(node)
            self.generic_visit(node)
            func_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if _is_get_event_loop_call(node) and not any(
                isinstance(f, ast.AsyncFunctionDef) for f in func_stack
            ):
                lines.append(node.lineno)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return lines


def find_undefined_entrypoint_names(source: str) -> list[tuple[int, str]]:
    """Namen (Zeilennummer, Bezeichner), die auf MODUL-EBENE einer Einstiegsdatei (`app/main.py`,
    `main.py`, ...) gelesen werden, ohne irgendwo im selben Modul gebunden (importiert, zugewiesen,
    als Funktion/Klasse definiert, ...) worden zu sein - der statische Vorläufer eines garantierten
    `NameError` beim Start.

    Realer Fund (ecotrack_ai, 2026-09-17): `app/main.py` registrierte `app.include_router(
    fleet_router)`/`ml_router`/`finops_router`, ohne die Module je zu importieren - `NameError:
    name 'fleet_router' is not defined` bei jedem App-Start. Weder die Handoff-Prüfung noch
    `_missing_local_python_imports()` (prüft nur, ob referenzierte IMPORTE existieren, nicht ob
    verwendete Namen überhaupt importiert wurden) fingen das ab; erst der Testlauf deckte es auf,
    nachdem bereits ein Handoff-Zyklus als abgeschlossen galt.

    Bewusst flow-insensitiv (prüft nur, ob ein Name IRGENDWO im Modul gebunden wird, nicht ob VOR
    seiner Verwendung) und auf Modul-Ebene beschränkt (Funktions-/Klassenkörper haben eigene
    Scoping-Regeln und werden hier nicht geprüft) - dieselbe konservative Grundhaltung wie die
    übrigen Checks in dieser Datei: ein NameError, der nur unter seltenen Laufzeitbedingungen
    auftritt, darf übersehen werden, aber ein gemeldeter Fund muss zuverlässig echt sein. Ein
    Wildcard-Import (`from x import *`) macht die Analyse unzuverlässig (der Stern könnte jeden
    Namen einführen) und schaltet sie komplett ab."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    bound: set[str] = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "self", "cls"}
    has_star_import = False

    class _BindingCollector(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            nonlocal has_star_import
            for alias in node.names:
                if alias.name == "*":
                    has_star_import = True
                else:
                    bound.add(alias.asname or alias.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            bound.add(node.name)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            bound.add(node.name)
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            bound.add(node.name)
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name:
                bound.add(node.name)
            self.generic_visit(node)

        def visit_Global(self, node: ast.Global) -> None:
            bound.update(node.names)

        def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
            bound.update(node.names)

        def visit_arg(self, node: ast.arg) -> None:
            bound.add(node.arg)

    _BindingCollector().visit(tree)
    if has_star_import:
        return []

    findings: list[tuple[int, str]] = []
    seen: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in bound and node.id not in seen:
                    seen.add(node.id)
                    findings.append((node.lineno, node.id))
    return findings

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
#
# Erweiterung (Logs-Tiefenanalyse logs/runs/ und logs/verification/): auf Windows scheitert
# `npm test` oft schon VOR jedem Testlauf, weil `npm`/`npx`/ein npm-Skript im PATH fehlt oder
# das npm-Skript in package.json selbst einen nicht gefundenen Befehl aufruft - cmd.exe meldet
# das auf Deutsch ("... ist entweder falsch geschrieben ...") oder Englisch ("is not recognized
# as an internal or external command"), POSIX-Shells mit "command not found". Das ist KEIN
# Testcode-Fehler, sondern dieselbe Klasse Umgebungs-/Konfigurationsproblem wie oben.
_NODE_ENV_ERROR_PATTERN = re.compile(
    r"Cannot use import statement outside a module"
    r"|Jest encountered an unexpected token"
    r"|Cannot find module '[^']+' from"
    r"|is not defined by \"exports\""
    r"|Der Befehl \"[^\"]+\" ist entweder falsch geschrieben"
    r"|ist entweder falsch geschrieben oder konnte nicht gefunden werden"
    r"|'[^']+' is not recognized as an internal or external command"
    r"|command not found",
    re.IGNORECASE,
)

# tsc hat kein natives JSON-Format – `--pretty false` liefert stattdessen dieses stabile,
# grep-bare Zeilenformat: "pfad(zeile,spalte): error TSxxxx: nachricht".
_TSC_ERROR_PATTERN = re.compile(r"^(.+?)\((\d+),(\d+)\): (error|warning) (TS\d+): (.+)$", re.MULTILINE)

# Realer Fund (incidentpilot-Projekt): `docker build` schlug mit "failed to connect to the
# docker API at npipe:////./pipe/dockerDesktopLinuxEngine; ... check if ... the daemon is
# running" fehl - Docker war lokal installiert (shutil.which("docker") findet die CLI), aber
# Docker Desktop lief nicht. Das landete bisher als ganz normaler ❌ Build-Fehlschlag im
# Verifikations-Report, ununterscheidbar von einem echten, im generierten Dockerfile liegenden
# Fehler - dabei sagt eine fehlende Daemon-Verbindung nichts über die Codequalität aus, genau
# wie ein fehlendes `docker`-Kommando selbst (siehe reason_skipped-Zweig oben in
# check_docker_build()). Erkennt die verbreitetsten Docker-/Podman-Daemon-Konnektivitätsfehler.
_DOCKER_DAEMON_UNAVAILABLE_RE = re.compile(
    r"cannot connect to the docker daemon"
    r"|(?:check if|is) the docker daemon is running"
    r"|failed to connect to the docker api"
    r"|error during connect.*(?:pipe|socket)"
    r"|docker daemon is not running"
    r"|Is the docker daemon running"
    # Realer Fund auditlog_sentinel 2026-09-10: Docker Desktop war nicht gestartet, die
    # Named-Pipe antwortete aber mit "request returned 500 Internal Server Error for API route
    # and version http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/_ping" - bisher als echter
    # Build-Fehler des Projekts gewertet.
    r"|dockerDesktop(?:Linux|Windows)Engine"
    r"|500 Internal Server Error for API route.*_ping",
    re.IGNORECASE,
)

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
    __test__ = False  # Verhindert fälschliche Pytest-Sammlung als Testklasse
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
class FrontendBuildReport:
    """
    Ergebnis eines echten `npm run build` für EIN gefundenes Frontend-Projekt (siehe
    RuntimeMixin.check_frontend_build()) - ein Projekt kann mehrere solcher Reports liefern
    (z.B. ein Frontend unter frontend/ UND eines im Root). Anders als RuntimeSmokeReport prüft
    dies den Produktions-Build (Bundler/Compiler wie Vite/webpack/tsc), nicht das Starten der
    laufenden App.
    """
    attempted: bool
    passed: bool = False
    directory: str = ""
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
    r"|in\s+(einer\s+)?echten\s+implementierung\s+w[üu]rde"
    # Neunter realer Fund (ChronosPulse-Analyse, 20260913): `app/utils/resilience.py` bestand
    # nur aus 5 Kommentarzeilen ("# Auszug aus app/utils/resilience.py" gefolgt von einer
    # Stichpunktliste, WAS die Datei enthalten sollte) statt der eigentlichen
    # CircuitBreaker-/ExponentialBackoff-Klassen - ein Entwurfs-/Auszugs-Marker, den keiner der
    # bisherigen Marker erkannte, weil er kein "hier würde"/"simuliert"/"not implemented"
    # enthält, sondern wie eine harmlose Datei-Kopfzeile aussieht.
    r"|auszug\s+aus\b"
    r"|implementierungsbeispiel\b"
    r"|implementation\s+example\b"
    # Achter realer Fund (mockforge-Projekt, Team-Retrospektive 2026-09-05): ein Agent ersetzte
    # den kompletten Funktionskörper von ProxyMiddleware.dispatch() durch elidierte
    # Kommentarzeilen ("# ... (Imports)", "# ... (Request-Handling)") statt echten Code -
    # syntaktisch gültige Kommentare, die aber sämtliche darunter liegenden Namen (hier:
    # AsyncSessionLocal/TrafficLog/body_bytes) undefiniert zurücklassen. Nur ruff (F821 in der
    # separaten CI-Prüfung) fing das zufällig ab, KEIN bisheriger Stub-Marker hier. Bewusst nur
    # eine Kommentarzeile, die (nach dem Kommentarzeichen) ausschließlich aus "..." besteht -
    # ein legitimer Kommentar, der zufällig drei Punkte enthält (z.B. "Lädt Daten ..."), hat
    # danach fast immer noch weiteren Fließtext, keinen Zeilenumbruch direkt nach "...".
    r"|^\s*(?:#|//)\s*\.\.\.\s*(?:\([^)]*\))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Dateiendungen, die check_completeness() nach Stub-Markern durchsucht - dieselben Sprachen,
# die auch der echte Lint-/SAST-Check abdeckt (Python/JS/TS immer relevant, Go/Rust/Ruby/Java
# als verbreitete Backend-Sprachen des Frameworks, siehe agents/backend_agent.py).
_STUB_SCAN_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".java"}

# Kommentar-Präfix je Dateiendung für _comment_only_stub_files() (completeness.py) - dieselben
# Sprachen wie _STUB_SCAN_EXTENSIONS oben. Block-Kommentare (/* ... */) werden bewusst nicht
# erkannt, um die Heuristik einfach zu halten (eine einzelne Zeile reicht als Marker).
_LINE_COMMENT_PREFIX_BY_EXTENSION: dict[str, str] = {
    ".py": "#", ".rb": "#",
    ".js": "//", ".jsx": "//", ".ts": "//", ".tsx": "//", ".go": "//", ".rs": "//", ".java": "//",
}

# Zehnter realer Fund (ChronosPulse-Analyse, 20260913, Empfehlung 3): Dateien wie das oben
# beschriebene `app/utils/resilience.py` bestehen NUR aus wenigen Kommentarzeilen (kein
# einziges echtes Code-Statement) - ein struktureller Stub, den kein Text-Marker allein
# zuverlässig erfasst (ein Kommentar mit "Auszug aus" fängt nur die eine konkret beobachtete
# Formulierung ab). `_comment_only_stub_files()` in completeness.py meldet jede nicht-leere
# Quelldatei, die AUSSCHLIESSLICH aus Kommentar-/Leerzeilen besteht und dabei unter dieser
# Zeilenschwelle bleibt - eine wirklich leere Datei (z.B. ein bewusst leeres `__init__.py`)
# bleibt unauffällig, weil sie gar keine Kommentarzeile enthält.
_COMMENT_ONLY_STUB_MAX_LINES = 10

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

# Dreizehnter realer Fund (docu_guard-Projekt, 2026-09-17): `tests/test_api.py` rief `POST
# /api/v1/documents` auf und erwartete Status 200/Audit-Action "CREATE", der tatsächliche
# Endpunkt lautete `@router.post("/upload", status_code=201)` mit Audit-Action "UPLOAD" - der
# Tester-Agent hatte Route, Methode und Statuscode frei erfunden statt aus dem Backend-Code
# gelesen. Zwei vorherige Prompt-Hinweise an agents/tester_agent.py verhinderten dieselbe
# Fehlerklasse nicht zuverlässig (siehe CHANGELOG-Eintrag); _ROUTE_DECL_RE (Backend-Dekoratoren)
# und _TEST_CLIENT_CALL_RE (Testsuite-Aufrufe) bilden zusammen die Grundlage für einen
# deterministischen Abgleich in core/verifier/completeness.py._test_requests_undeclared_routes(),
# statt sich erneut allein auf einen Prompt-Hinweis zu verlassen.
_ROUTE_DECL_RE = re.compile(
    r"^\s*@(?:[A-Za-z_]\w*)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']*)[\"']",
    re.IGNORECASE | re.MULTILINE,
)
# Nur Aufrufe auf einem Objekt, dessen Name auf "client" endet (TestClient/AsyncClient-Konvention
# von FastAPI/Starlette/httpx) - schließt bewusst z.B. `session.post(...)` (verbreitet für
# ECHTE ausgehende HTTP-Aufrufe an Drittanbieter-APIs innerhalb eines Test-Mocks) aus, um dort
# keinen Fehlalarm auszulösen.
_TEST_CLIENT_CALL_RE = re.compile(
    r"\b(\w*client\w*)\.(get|post|put|patch|delete)\(\s*(f)?[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)
_IO_CALL_MARKERS = (
    "session", "db.", "db_", "cursor", "execute(", "query(", ".save(", "insert(",
    "update(", "delete(", "open(", "s3", "boto3", "redis", "requests.", "httpx.",
    "aiofiles", "read_text(", "write_text(", "read_bytes(", "write_bytes(",
    ".find(", ".find_one(", "select(", "commit(", "flush(", "orm", "prisma",
    "os.remove", "shutil.", "upload_fileobj",
    # Elfter realer Fund (incidentpilot-Projekt, 2026-09-06): der Handler selbst enthielt keinen
    # direkten I/O-Aufruf, delegierte die Persistenz aber korrekt per FastAPI-Idiom an
    # `background_tasks.add_task(save_incident, ...)` - ein etablierter, verbreiteter Weg,
    # I/O NACH dem Response-Versand auszuführen, kein Stub. Ohne diesen Marker meldete der Check
    # einen Falsch-Positiv für jeden Handler, der Persistenz bewusst in einen Background-Task
    # auslagert.
    "add_task(",
)
# Zweite, eigene Markergruppe für die verbreitete In-Memory-Store-Persistenz kleiner Demo-Apps
# (z.B. `notes_db[note_id] = note`, `monitor.checks.pop(id, None)`, `monitor.add_check(check)`)
# - real beobachtet als Falsch-Positiv-Quelle beim ersten Entwurf dieses Checks: ein `dict` als
# Store ist keine Stub-Implementierung, nur kein DB-/Storage-Framework. Separates Muster statt
# Teil von _IO_CALL_MARKERS, weil es strukturell (Subscript-Zuweisung/Methodenaufruf) statt rein
# textuell erkannt wird.
# Vierzehnter realer Fund (hyperion_metrics-Projekt, 2026-09-17): `DELETE /api/v1/alerts/{rule_id}`
# rief `alert_engine.remove_rule(rule_id)` auf - eine echte In-Memory-Mutation, kein Stub. Das
# Muster verlangte bis dahin exakt `.remove(` OHNE Suffix (anders als `.add\w*\(`/`.update\w*\(`/
# etc., die bewusst einen Methodennamen-Suffix erlauben), sodass jede sprechend benannte Remove-
# Methode (`remove_rule`, `remove_item`, ...) fälschlich als fehlende Persistenz gemeldet wurde -
# der Fixversuch-Loop erkannte danach korrekt "keine Veränderung" (der Code war nie kaputt) und
# brach ab, wodurch das gesamte Projekt trotz funktionierendem Handler auf Rot stand. `\w*` nach
# `.remove` ergänzt, analog zu den übrigen Mustern dieser Gruppe.
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
    r"|\.remove\w*\("
    r"|\.insert\w*\("
    # Team-Optimierung 2026-09-17 (hyperion_metrics-Root-Cause): `.delete...(`/`.clear...(` auf
    # einer In-Memory-Engine/Registry (z.B. `alert_engine.delete_rule(id)`, `cache.clear()`)
    # ist dieselbe Klasse valider Zustandsmutation wie `.remove...(`/`.pop(`, wurde bisher aber
    # nicht erkannt - ein schreibender Handler, der ausschließlich so mutiert, wurde fälschlich
    # als I/O-los gemeldet, obwohl die Architektur laut ADR bewusst auf eine In-Memory-Engine
    # statt DB/Datei/HTTP setzt.
    r"|\.delete\w*\("
    r"|\.clear\w*\(",
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

# Fehlalarm-Korrektur (Live-Abgleich gegen alle workspace/-Projekte, Team-Retrospektive
# 2026-09-05, real beobachtet an `fastapi-task-mgmt`): ein Projekt mit Alembic-Migrationen legt
# konventionsgemäß ein EIGENES Top-Level-Verzeichnis `alembic/` an (Migrationsskripte) - das
# kollidiert im Namen exakt mit dem gleichnamigen PyPI-Paket `alembic`. `alembic/env.py`
# importiert dort `from alembic import context` - gemeint ist das ECHTE, pip-installierte Paket
# (das `context`-Symbol wird von Alembic selbst zur Laufzeit per `sys.modules`-Manipulation
# injiziert, existiert nirgends als Datei), nicht das lokale `alembic/`-Verzeichnis des
# Projekts. _local_top_level_names() hielt das lokale Verzeichnis bisher fälschlich für ein
# eigenes, lokales Python-Paket und meldete den Import als "verweist auf keine existierende
# Datei" - eine reine Namenskollision, kein echter Fund. Bewusst als eigene, kleine Ausnahme
# (nicht als generelle Regel "jedes Verzeichnis mit einem PyPI-Namen ausschließen") - "alembic"
# ist die einzige in der Praxis verbreitete Alles-oder-Nichts-Kollision dieser Art.
_LOCAL_DIR_THIRDPARTY_NAME_COLLISIONS = frozenset({"alembic"})
_MANIFEST_FILENAMES = ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "poetry.lock")
_PY_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", re.MULTILINE)

# Siebter realer Fund (Team-Retrospektive 2026-09-05, logpulse-Projekt): der bisherige
# _missing_dependency_manifest()-Check prüft nur, ob IRGENDEIN Manifest existiert - nicht, ob es
# die tatsächlich importierten Pakete auch AUFLISTET. logpulse importierte in seiner Testsuite
# `pytest`/`httpx` und nutzte `@pytest.mark.asyncio`, aber requirements.txt enthielt keines der
# drei (auch nicht `pytest-asyncio`) - jeder Testlauf schlug deshalb zuverlässig fehl, ohne dass
# ein bisheriger Check das VOR der teuren echten Testausführung erkannt hätte. Bewusst nur eine
# kuratierte Allowlist bekannter, eindeutiger Pakete (statt jeden Drittanbieter-Import zu prüfen):
# viele Importnamen sind keine 1:1-Entsprechung ihres PyPI-Paketnamens (z.B. `google.cloud.x`) und
# ein sicherer Treffer ist hier wichtiger als Vollständigkeit - ein Fehlalarm bei einem exotischen
# Paket wäre schlimmer als ein unentdeckter Fund außerhalb dieser Liste.
# Einzige Quelle: core/known_pitfalls.py (PEP-503-normalisiert, wie _KNOWN_PACKAGE_NAMES).
_IMPORT_TO_PACKAGE_NAME: dict[str, str] = {
    name: normalize_package_name(pkg) for name, pkg in IMPORT_TO_PACKAGE.items()
}
_KNOWN_PACKAGE_NAMES = frozenset({
    "fastapi", "flask", "django", "uvicorn", "gunicorn",
    "sqlalchemy", "aiosqlite", "asyncpg", "psycopg2", "psycopg2-binary", "pymongo", "motor",
    "redis", "celery", "alembic",
    "pytest", "pytest-asyncio", "pytest-cov", "httpx", "requests", "aiohttp", "respx",
    "boto3", "python-dotenv", "pyjwt", "python-jose", "passlib",
    "bcrypt", "cryptography", "pyyaml", "typer", "rich", "docker",
    "python-multipart", "numpy", "pandas", "slowapi", "circuitbreaker", "pybreaker", "tenacity",
    # BEWUSST NICHT enthalten, obwohl sie oft direkt importiert werden: `starlette`/`pydantic`
    # (real beobachtet beim Live-Abgleich gegen ALLE workspace/-Projekte, Team-Retrospektive
    # 2026-09-05 - beide sind Pflicht-Abhängigkeiten von `fastapi` selbst, `pip install fastapi`
    # installiert sie IMMER automatisch mit, auch wenn requirements.txt nur "fastapi" auflistet),
    # `jinja2`/`click` (Pflicht-Abhängigkeiten von `flask` bzw. `typer`/`uvicorn[standard]`) -
    # ein direkter Import ohne expliziten Manifest-Eintrag ist hier so verbreitet und
    # funktioniert so zuverlässig, dass eine Meldung nur Rauschen wäre (10 von 21 echten
    # workspace-Projekten hätten sonst einen Fehlalarm bekommen, keines davon tatsächlich
    # kaputt). Dieselbe konservative Grundhaltung wie überall in dieser Datei.
})

# Async-Testfunktionen (`@pytest.mark.asyncio` oder eine `async def test_...`) benötigen zwingend
# das `pytest-asyncio`-Plugin (oder `anyio` mit dessen eigenem Marker) installiert - ohne das
# bricht jeder so markierte Test mit einem Fixture-/Marker-Fehler ab, unabhängig davon, ob der
# eigentliche Testcode korrekt ist. Derselbe logpulse-Fund wie oben.
_PYTEST_ASYNC_TEST_RE = re.compile(r"@pytest\.mark\.asyncio\b|^\s*async\s+def\s+test_", re.MULTILINE)

# Zweiter Teil desselben logpulse-Funds: `app/database.py` definierte eine ASYNCHRONE Engine
# (`create_async_engine`), `app/models.py` daneben eine eigene SYNCHRONE Engine
# (`create_engine`) samt eigener `Base = declarative_base()` - zwei parallele, inkompatible
# Metadata-Registries im selben Projekt. Rein regelbasiert (kein AST nötig): die bloße
# Koexistenz beider Engine-Arten bzw. mehrerer `declarative_base()`-Definitionen im selben
# Projekt ist so gut wie nie beabsichtigt.
_SQLA_SYNC_ENGINE_RE = re.compile(r"\bcreate_engine\s*\(")
_SQLA_ASYNC_ENGINE_RE = re.compile(r"\bcreate_async_engine\s*\(")
_SQLA_DECLARATIVE_BASE_RE = re.compile(
    r"\bdeclarative_base\s*\(|class\s+\w+\s*\(\s*(?:orm\.)?DeclarativeBase\s*\)"
)

# Zehnter realer Fund (incidentpilot-Projekt, 2026-09-06): `app/database.py` verwendete die DSN
# `postgresql+asyncpg://...` als String-Literal, aber `requirements.txt` listete nur
# `psycopg2-binary` (den SYNCHRONEN Treiber) statt `asyncpg` - SQLAlchemy lädt den Treiber erst
# zur LAUFZEIT anhand des DSN-Schemas dynamisch nach (`__import__("asyncpg")` in
# sqlalchemy/dialects/postgresql/asyncpg.py), es gibt also NIRGENDS ein statisches
# `import asyncpg`, das _collect_third_party_imports()/_missing_known_packages_in_manifest()
# hätte finden können. Diese Regex greift stattdessen direkt am DSN-Schema selbst an - jedes
# `<dialekt>+<treiber>://`-Literal benennt seinen benötigten Treiber explizit im String selbst.
_SQLA_DSN_DRIVER_RE = re.compile(
    r"""["']((?:postgresql|mysql|mariadb|sqlite)\+(\w+)):/{2,4}"""
)
# DSN-Treibername -> tatsächlicher PyPI-Paketname, wo beide voneinander abweichen (sonst wird
# der Treibername selbst als Paketname angenommen, z.B. "asyncpg" -> "asyncpg").
_SQLA_DRIVER_TO_PACKAGE_NAME: dict[str, str] = {
    "psycopg2": "psycopg2-binary",
    "pysqlite": "",  # Teil der Python-Standardbibliothek, kein PyPI-Paket nötig
    "aiosqlite": "aiosqlite",
    "asyncpg": "asyncpg",
    "aiomysql": "aiomysql",
    "asyncmy": "asyncmy",
    "pymysql": "pymysql",
}

# Team-Optimierung (Retrospektive 2026-09-07, taskboard-Governance-Fund): `TrustedHostMiddleware
# (allowed_hosts=["*"])` erlaubt JEDEN Host-Header und hebelt damit den eigentlichen Zweck der
# Middleware (Schutz vor Host-Header-Injection/DNS-Rebinding) komplett aus - ein Muster, das
# bereits in einem echten Projekt vom Governance-Review post-hoc gefunden wurde. Rein
# regelbasiert per Regex statt AST (dieselbe Abwägung wie beim Rest dieser Datei: das Argument
# ist fast immer ein Literal, ein echter Parser lohnt sich für ein einzelnes Schlüsselwort-Muster
# nicht). Erfasst sowohl `["*"]` als auch `allowed_hosts="*"` (String statt Liste).
_TRUSTED_HOST_WILDCARD_RE = re.compile(
    r"TrustedHostMiddleware[^)]*allowed_hosts\s*=\s*(?:\[\s*[\"']\*[\"']\s*,?\s*\]|[\"']\*[\"'])"
)
# CORSMiddleware(allow_origins=["*"], allow_credentials=True) ist die eigentlich gefaehrliche
# Kombination (nicht der Wildcard allein): mit Credentials erlaubt das JEDER Website im Browser,
# im Namen eines eingeloggten Nutzers Anfragen zu stellen - moderne Browser verweigern diese
# Kombination inzwischen zwar serverseitig oft selbst, aber verlassen sollte man sich darauf
# nicht. Beide Argumente koennen in beliebiger Reihenfolge auftreten, deshalb zwei Regexe statt
# eines starren "allow_origins...allow_credentials"-Musters.
_CORS_WILDCARD_ORIGIN_RE = re.compile(r"CORSMiddleware[^)]*allow_origins\s*=\s*\[\s*[\"']\*[\"']")
_CORS_ALLOW_CREDENTIALS_RE = re.compile(r"CORSMiddleware[^)]*allow_credentials\s*=\s*True")

# Team-Optimierung (Retrospektive 2026-09-08, opspilot-Governance-Fund): eine Resilience-/
# Circuit-Breaker-Dekoration fängt `CircuitBreakerError` (oder eine verwandte Retry-/Resilience-
# Ausnahme) ab und liefert im Fallback-Zweig ein rohes `dict`-Literal zurück, während die
# dekorierte Funktion laut Signatur ein Pydantic-Modell (`-> WorkflowRecommendation:`) zurückgeben
# muss - jeder Aufrufer, der `.attribut`-Zugriff oder Pydantic-Validierung auf dem Rückgabewert
# erwartet, bekommt bei einem offenen Circuit Breaker einen `AttributeError`/Validierungsfehler
# statt der erwarteten Fehlerbehandlung. Rein regelbasiert: sucht ein `except`, dessen
# Ausnahmename auf Circuit-Breaker/Resilience/Retry hindeutet, gefolgt (innerhalb weniger Zeilen,
# noch im selben Block) von einem `return {`-Dict-Literal.
_RESILIENCE_FALLBACK_EXCEPT_RE = re.compile(
    r"except\s+\w*(?:CircuitBreaker|Resilience|Retry)\w*(?:\s+as\s+\w+)?\s*:"
)
_DICT_LITERAL_RETURN_RE = re.compile(r"^\s*return\s*\{")

# Team-Optimierung (KI-Team-Weiterentwicklung, echter Fund: agent_governance-Projekt,
# 2026-09-09 - `SASTAdapter` gibt ein `Dict` zurück statt das in `schemas.py` definierte
# `SASTReport`-Modell zu nutzen): _RESILIENCE_FALLBACK_EXCEPT_RE oben erkennt dasselbe
# Fehlerbild bereits, aber NUR innerhalb eines Resilience-/Circuit-Breaker-`except`-Blocks
# (opspilot-Fund, 2026-09-08). Der agent_governance-Fund war kein Resilience-Fallback, sondern
# schlicht die normale Implementierung einer Methode - CompletenessMixin._direct_dict_return_
# type_mismatch() prüft deshalb ALLGEMEIN jede Funktion/Methode, deren Rückgabetyp-Annotation
# ein einfacher, groß geschriebener Name ist (Heuristik: "sieht wie ein eigenes Pydantic-
# Modell/Dataclass aus"), gegen jede eigene `return`-Stelle. Diese Menge grenzt die generischen/
# Builtin-Rückgabetypen aus, für die ein Dict-Literal legitim ist (u.a. `dict`/`Dict` selbst,
# sowie Namen, die auf ein TypedDict/JSON-artiges Ergebnis hindeuten) - nur ein NICHT hier
# gelisteter, groß geschriebener Name gilt als "modellartig" genug für einen Fund.
_GENERIC_RETURN_TYPE_NAMES = frozenset({
    "dict", "Dict", "list", "List", "set", "Set", "tuple", "Tuple", "str", "int", "float",
    "bool", "bytes", "None", "Any", "object", "Mapping", "MutableMapping", "JSON", "JSONType",
    "Optional", "Union", "Callable", "Iterable", "Iterator", "Generator", "Sequence",
})

# Dieselbe Team-Optimierung, zweiter Teil (logpulse-Fund vom 2026-09-05, bisher nie umgesetzt):
# `create_async_engine()` braucht das Paket `greenlet` zur LAUFZEIT, um synchronen DBAPI-Code aus
# async Kontext heraus aufzurufen (SQLAlchemy's Greenlet-basierte async-Bridge) - der Code
# importiert `greenlet` aber NIRGENDS explizit (SQLAlchemy lädt es intern nach), weshalb eine rein
# importbasierte Prüfung (_missing_known_packages_in_manifest()) das nie findet. Ohne
# `greenlet` in requirements.txt schlägt jeder echte DB-Zugriff mit "the greenlet library is
# required to use this function" fehl - ein Laufzeitfehler, der beim reinen Import-Check der
# Anwendung (kein DB-Zugriff nötig) unentdeckt bleibt und erst in echten Endpunkt-/Testläufen
# auffällt.
_GREENLET_PACKAGE_NAME = "greenlet"

# Fünfter realer Fund (Team-Retrospektive, taskpulse-Projekt): _missing_local_python_imports()
# (siehe completeness.py) prüfte bisher NUR Python - dieselbe Fehlerklasse ("lokaler Import
# verweist auf eine nie erzeugte Datei") passiert genauso in JS/TS-Frontend-Projekten, z.B.
# `import { formatDate } from './utils/date'`, wenn `utils/date.js` nie angelegt wurde. Erkennt
# relative ES-Modul-Importe (`import ... from './x'`, `export ... from './x'`), dynamische
# Importe (`import('./x')`) und CommonJS-`require('./x')` - bewusst NUR relative Pfade
# (beginnend mit "." oder "/"), damit npm-Paket-Importe ("from 'react'") nie fälschlich als
# lokale Datei geprüft werden (dieselbe konservative Abgrenzung wie local_top_level bei Python).
_JS_RELATIVE_ES_IMPORT_RE = re.compile(
    r"(?:import|export)(?:[^'\";\n]*?\bfrom\s*)?\s*['\"](\.[^'\"]+)['\"]"
)
_JS_RELATIVE_REQUIRE_RE = re.compile(r"require\(\s*['\"](\.[^'\"]+)['\"]\s*\)")
_JS_RELATIVE_DYNAMIC_IMPORT_RE = re.compile(r"import\(\s*['\"](\.[^'\"]+)['\"]\s*\)")
# Endungen, die _missing_local_js_imports() als "eigenständig lauffähige JS/TS-Quelldatei"
# behandelt - ein Import OHNE Endung (z.B. "./utils/date") wird gegen JEDE dieser Endungen
# UND gegen "<pfad>/index.<endung>" (Verzeichnis-Import) geprüft. Ein Import MIT einer anderen
# Endung (z.B. "./logo.svg", "./styles.css", "./data.json") wird NICHT geprüft - solche Importe
# hängen von der jeweiligen Bundler-Konfiguration ab (Asset-/CSS-/JSON-Loader), die dieses
# Framework nicht kennt; ein Fehlalarm dort wäre schlimmer als eine übersehene fehlende Datei.
_JS_MODULE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# Sechster realer Fund (Team-Retrospektive, zweite Runde): _scan_write_routes_missing_io()
# (Python, siehe oben) hat kein JS/TS-Pendant - ein Express/Fastify/Koa-Handler mit hartcodierter
# Literal-Rückgabe statt echter Persistenz (derselbe cloudvault-Fund wie bei Python, nur im
# Node-Backend) blieb bisher unentdeckt. Erkennt schreibende Routen-Registrierungen
# (`app.post(...)`/`router.put(...)`/...) mit INLINE-Handler-Funktion - eine Referenz auf eine
# benannte Funktion (`app.post('/x', createUser)`) wird bewusst NICHT geprüft, weil deren Body
# nicht in derselben Zeile/demselben Ausdruck steht (siehe _scan_js_write_routes_missing_io()-
# Docstring in completeness.py für die genaue Abgrenzung).
_JS_WRITE_ROUTE_CALL_RE = re.compile(
    r"\b(?:app|router)\.(?:post|put|patch|delete)\(\s*(['\"])([^'\"]*)\1", re.IGNORECASE,
)
_JS_IO_CALL_MARKERS = (
    "session", "db.", "db_", "cursor", ".execute(", ".query(", ".save(", ".insert(",
    ".update(", ".delete(", ".find(", ".findOne(", ".findById(", ".findByIdAndUpdate(",
    ".findByIdAndDelete(", "prisma.", "knex(", "mongoose", "redis", "s3", "fetch(",
    "axios.", "fs.write", "fs.append", "writeFile", "readFile", "INSERT INTO", "UPDATE ",
    "DELETE FROM",
)
_JS_IO_MUTATION_RE = re.compile(
    r"\w+\[[^\]\n]+\]\s*="  # z.B. notesById[id] = ...
    r"|\.push\("
    r"|\.splice\("
    r"|\.set\("
    r"|\.delete\("
    r"|\.pop\("
)


@dataclass
class CompletenessIssue:
    """Ein einzelner Stub-/Platzhalter-Fund oder ein fehlender, in README referenzierter Pfad.

    `kind` (Team-Optimierung, vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund
    am event_relay-Lauf 2026-09-06): agents/orchestrator/verification.py filterte die "lokaler
    Import schlägt fehl"-Funde bisher per Substring-Suche `"existierendes lokales" in message`
    heraus, um sie VOR jedem Testlauf UND in den Governance-Fix-Prompt gezielt einzuspeisen.
    core/verifier/completeness.py._check_symbols_in_module_file() formuliert einen fehlenden
    SYMBOL-Import (z.B. `from app.resilience import resilience`, wenn `resilience` dort gar
    nicht mehr definiert ist) aber bewusst als "... verweist auf kein ... definiertes/
    importiertes Symbol" - OHNE die Zeichenfolge "existierendes lokales". Genau diese
    Fehlerklasse (real beobachtet: `RateLimitMiddleware`/`SimpleRateLimiter` bei
    zeiterfassung_app UND `resilience` bei event_relay) fiel dadurch durch beide Filter, obwohl
    check_completeness() sie bereits korrekt erkannte - ein rein textueller Filter auf
    freihändig formulierte deutsche Fehlermeldungen ist von Natur aus fragil. `kind` ist ein
    stabiles, maschinenlesbares Tag für genau diese Fund-KLASSE ("missing_local_import" für
    alle drei Varianten: fehlendes Modul/Paket, fehlendes Submodul, fehlendes Symbol in einer
    existierenden Datei) - leer ("") für jede andere, nicht dafür gedachte Fund-Art."""
    file_path: str
    line_number: int = 0
    message: str = ""
    kind: str = ""


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
