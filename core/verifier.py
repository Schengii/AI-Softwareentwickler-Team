"""
core/verifier.py – Echte Verifikation statt Keyword-Raten

Ersetzt die alte, rein textbasierte Fix-Schleife (die nur nach Schlagworten
wie "kritischer fehler" im Reviewer-Text suchte und danach blind
backend/frontend/database neu beauftragte). Stattdessen:

1. Legt bei Bedarf eine isolierte virtuelle Umgebung im Projekt an und
   installiert requirements.txt wirklich (echte Dependency-Installation).
   Für Node/npm-Projekte (package.json) läuft dieselbe echte Installation
   über `npm ci`/`npm install`.
2. Führt die tatsächliche Testsuite aus (pytest, falls verfügbar, sonst
   unittest discover; für Node-Projekte `npm test`) und liest das reale
   Ergebnis (exit_code/stdout/stderr).
3. Parst bei Fehlschlägen die echten pytest-/unittest-/npm-test-Ausgaben und
   Tracebacks, um herauszufinden, WELCHE Quelldateien betroffen sind –
   als Grundlage dafür, den Fix gezielt an den Agenten zurückzuspielen,
   der genau diese Datei geschrieben hat (statt an alle Dev-Agenten blind).

Realer Fund: bisher wurde AUSSCHLIESSLICH Python-Code echt verifiziert
(test_*.py). Ein vom frontend/mobile-Agenten erzeugtes JS/TS-Projekt lief nie
durch einen echten `npm test` – "keine Tests gefunden" tauchte selbst dann
auf, wenn eine vollständige, echt ausführbare npm-Testsuite existierte.

Zusätzlich: check_dependency_vulnerabilities() ersetzt die bisherige rein
LLM-basierte Einschätzung des security-Agenten zu Abhängigkeits-Risiken durch
einen echten Scan (pip-audit/npm audit) gegen eine öffentliche Advisory-
Datenbank – kein Raten mehr, ob eine gepinnte Paketversion bekannte CVEs hat.

Und: check_lint() prüft generierten Code jetzt auch tatsächlich mit echten
Tools (ruff für Python – immer, braucht keine Projekt-Konfiguration; ESLint/
tsc für Node – nur wenn das Projekt sie selbst bereits als Dev-Abhängigkeit +
Konfiguration mitbringt, keine ungefragte Meinungsänderung am Projekt-Stil).
Bisher lief ruff.toml NUR gegen den Framework-Code selbst (workspace/ dort
bewusst ausgeschlossen) – generierter Code hatte dadurch überhaupt keine
automatische Stil-/Fehlerprüfung.

Und: check_sast() ersetzt die bisherige rein LLM-basierte Einschätzung des security-Agenten
zu Schwachstellen im SELBST GESCHRIEBENEN Code (Freitext-Vermutungen ohne Datei/Zeile) durch
einen echten statischen Scan (bandit für Python) – dasselbe Prinzip, das
check_dependency_vulnerabilities() bereits für Fremdpaket-CVEs etabliert hat.

Und: check_licenses() ersetzt die bisherige rein LLM-basierte Lizenz-Tabelle des
compliance-Agenten ("MIT/AGPL 🔴", geraten) durch einen echten Scan der tatsächlich
installierten Paket-Lizenzen (pip-licenses für Python) inkl. einfacher Copyleft-Heuristik
(GPL/AGPL/LGPL/MPL/CDDL/EUPL/SSPL) – kein Raten mehr, welche Lizenz ein Fremdpaket wirklich hat.

Und: check_load_test() führt die vom performance-Agenten geschriebenen k6-/Locust-Lastentest-
Skripte tatsächlich AUS (bisher landeten sie ungeprüft im Projekt, niemand wusste, ob sie
überhaupt liefen) – startet die generierte App auf einem freien Port und lässt einen kurzen,
wenige Sekunden dauernden Smoke-Lasttest dagegen laufen, kein vollständiger Lasttest.

Und: check_accessibility() (core/browser_verifier.py.verify_accessibility()) ersetzt die
bisherige rein LLM-basierte Einschätzung des accessibility-Agenten (Freitext-Checkliste ohne
konkreten Fundort) durch einen echten axe-core-Scan (WCAG 2.x) gegen eine echt gerenderte
Playwright-Seite – dasselbe Prinzip wie check_sast() für Security, nur für Barrierefreiheit.
"""

import csv
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from core.code_sandbox import CodeSandbox, ExecutionResult

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


class ProjectVerifier:
    """Installiert Abhängigkeiten isoliert und führt die reale Testsuite eines Projekts aus."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()

    def _venv_python(self) -> Path:
        venv_dir = self.project_dir / VENV_DIRNAME
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _requirements_file(self) -> Path | None:
        for name in ("requirements.txt", "requirements-dev.txt"):
            candidate = self.project_dir / name
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
        return None

    def ensure_environment(self, timeout_seconds: float = 120.0) -> str:
        """
        Installiert echte Abhängigkeiten für JEDEN im Projekt gefundenen Stack:
        - Python: legt bei vorhandener requirements.txt eine isolierte venv an und
          installiert per pip.
        - Node: für jedes gefundene package.json mit "test"-Skript per `npm ci`
          (bei vorhandener package-lock.json, deterministisch) oder `npm install`.
        Gibt eine kombinierte Statuszeile zurück (leer, wenn nichts zu tun war, z.B.
        ein reines Textprojekt ohne requirements.txt/package.json).
        """
        logs: list[str] = []
        req_file = self._requirements_file()
        if req_file:
            logs.append(self._ensure_python_environment(req_file, timeout_seconds))
        for node_dir in self._find_node_projects():
            logs.append(self._ensure_node_environment(node_dir, timeout_seconds))
        if self._has_rust_project():
            logs.append(self._ensure_rust_environment(timeout_seconds))
        if self._has_go_project():
            logs.append(self._ensure_go_environment(timeout_seconds))
        return "\n".join(log for log in logs if log)

    def _has_rust_project(self) -> bool:
        return (self.project_dir / "Cargo.toml").exists()

    def _has_go_project(self) -> bool:
        return (self.project_dir / "go.mod").exists()

    def _ensure_rust_environment(self, timeout_seconds: float) -> str:
        if shutil.which("cargo") is None:
            return "⚠️ `cargo` ist auf diesem System nicht installiert/verfügbar – Rust-Check übersprungen."
        result = CodeSandbox.run_command(["cargo", "check"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        status = "✅" if result.exit_code == 0 else "⚠️"
        return f"{status} cargo check (exit_code={result.exit_code})"

    def _ensure_go_environment(self, timeout_seconds: float) -> str:
        if shutil.which("go") is None:
            return "⚠️ `go` ist auf diesem System nicht installiert/verfügbar – Go-Abhängigkeiten übersprungen."
        result = CodeSandbox.run_command(["go", "mod", "download"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        status = "✅" if result.exit_code == 0 else "⚠️"
        return f"{status} go mod download (exit_code={result.exit_code})"

    def _ensure_python_environment(self, req_file: Path, timeout_seconds: float) -> str:
        venv_python = self._venv_python()
        if not venv_python.exists():
            create_result = CodeSandbox.run_command(
                [sys.executable, "-m", "venv", str(self.project_dir / VENV_DIRNAME)],
                cwd=self.project_dir,
                timeout_seconds=60.0,
            )
            if create_result.exit_code != 0:
                return f"⚠️ Konnte keine isolierte venv anlegen (nutze System-Interpreter als Fallback): {create_result.stderr[:300]}"

        target_python = venv_python if venv_python.exists() else Path(sys.executable)
        install_result = CodeSandbox.run_command(
            [str(target_python), "-m", "pip", "install", "-q", "-r", str(req_file)],
            cwd=self.project_dir,
            timeout_seconds=timeout_seconds,
        )
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        tail = (install_result.stdout + install_result.stderr).strip()[-800:]
        return f"{status} pip install -r {req_file.name} (exit_code={install_result.exit_code})" + (f"\n{tail}" if install_result.exit_code != 0 else "")

    def _ensure_node_environment(self, node_dir: Path, timeout_seconds: float) -> str:
        rel = self._relative_label(node_dir)
        if shutil.which("npm") is None:
            return f"⚠️ `npm` ist auf diesem System nicht installiert/verfügbar – Node-Abhängigkeiten ({rel}) übersprungen."

        command = ["npm", "ci"] if (node_dir / "package-lock.json").exists() else ["npm", "install"]
        install_result = CodeSandbox.run_command(command, cwd=node_dir, timeout_seconds=timeout_seconds)
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        tail = (install_result.stdout + install_result.stderr).strip()[-800:]
        label = f"{' '.join(command)} ({rel})"
        return f"{status} {label} (exit_code={install_result.exit_code})" + (f"\n{tail}" if install_result.exit_code != 0 else "")

    def _relative_label(self, directory: Path) -> str:
        rel = directory.relative_to(self.project_dir)
        return "." if str(rel) == "." else str(rel).replace("\\", "/")

    def _find_node_projects(self) -> list[Path]:
        """
        Findet alle package.json-Verzeichnisse im Projekt (node_modules & Co. ausgeschlossen),
        die ein "test"-Skript deklarieren – nur solche sind über `npm test` echt ausführbar.
        Ein package.json ohne "test"-Skript wird bewusst ignoriert statt eines Fehlschlags,
        genau wie ein Python-Projekt ohne test_*.py-Dateien.
        """
        projects: list[Path] = []
        for pkg_json in self.project_dir.rglob("package.json"):
            if any(part in _IGNORED_DIRS for part in pkg_json.relative_to(self.project_dir).parts):
                continue
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data.get("scripts"), dict) and data["scripts"].get("test"):
                projects.append(pkg_json.parent)
        return projects

    def _resolve_python(self) -> str:
        venv_python = self._venv_python()
        return str(venv_python) if venv_python.exists() else sys.executable

    def _find_python_test_files(self) -> list[Path]:
        return [
            f for f in list(self.project_dir.rglob("test_*.py")) + list(self.project_dir.rglob("*_test.py"))
            if not any(part in _IGNORED_DIRS for part in f.parts)
        ]

    def run_tests(self, timeout_seconds: float = 60.0) -> VerificationReport:
        """
        Führt die echte Testsuite JEDES im Projekt gefundenen Stacks aus. Kein Keyword-
        Matching – reales exit_code/stdout/stderr, kombiniert über alle Stacks. Ein Projekt
        gilt insgesamt als bestanden, wenn ALLE gefundenen Testsuiten (Python UND/ODER Node)
        bestehen – ein grüner Backend-Test bei rotem Frontend-Test darf nicht als "bestanden"
        durchgehen.
        """
        start = time.monotonic()
        python_test_files = self._find_python_test_files()
        node_projects = self._find_node_projects()
        npm_available = shutil.which("npm") is not None
        runnable_node_projects = node_projects if npm_available else []

        has_rust = self._has_rust_project()
        has_go = self._has_go_project()
        cargo_available = shutil.which("cargo") is not None
        go_available = shutil.which("go") is not None

        if not python_test_files and not runnable_node_projects and not (has_rust and cargo_available) and not (has_go and go_available):
            if node_projects and not npm_available:
                reason = "npm-Test-Skript(e) gefunden, aber `npm` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            elif has_rust and not cargo_available:
                reason = "Cargo.toml gefunden, aber `cargo` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            elif has_go and not go_available:
                reason = "go.mod gefunden, aber `go` ist auf diesem System nicht installiert/verfügbar – Verifikation übersprungen."
            else:
                reason = 'Keine Testdateien (test_*.py), kein npm-Test-Skript und kein Rust/Go-Projekt gefunden – Verifikation übersprungen.'
            return VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="",
                duration_seconds=time.monotonic() - start, reason_skipped=reason,
            )

        passed = True
        exit_code = 0
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        failures: list[TestFailure] = []

        if python_test_files:
            python_exe = self._resolve_python()
            exec_result = self._run_pytest_or_unittest(python_exe, timeout_seconds)
            stdout_chunks.append(f"--- Python (pytest/unittest) ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.extend(self._parse_python_failures(exec_result))

        for node_dir in runnable_node_projects:
            exec_result = CodeSandbox.run_command(
                ["npm", "test", "--silent"], cwd=node_dir, timeout_seconds=timeout_seconds,
            )
            rel = self._relative_label(node_dir)
            stdout_chunks.append(f"--- npm test ({rel}) ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.extend(self._parse_node_failures(exec_result, node_dir))

        if has_rust and cargo_available:
            exec_result = CodeSandbox.run_command(
                ["cargo", "test"], cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
            stdout_chunks.append(f"--- cargo test ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.append(TestFailure(test_id="cargo test", message=(exec_result.stderr or exec_result.stdout)[-800:]))

        if has_go and go_available:
            exec_result = CodeSandbox.run_command(
                ["go", "test", "-v", "./..."], cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
            stdout_chunks.append(f"--- go test ---\n{exec_result.stdout}")
            stderr_chunks.append(exec_result.stderr)
            if exec_result.exit_code != 0:
                passed = False
                exit_code = exit_code or exec_result.exit_code
                failures.append(TestFailure(test_id="go test", message=(exec_result.stderr or exec_result.stdout)[-800:]))

        if node_projects and not npm_available:
            stdout_chunks.insert(0, "⚠️ npm nicht verfügbar – gefundene npm-Test-Skripte wurden übersprungen.")

        return VerificationReport(
            ran=True, passed=passed, exit_code=exit_code,
            stdout="\n".join(stdout_chunks), stderr="\n".join(stderr_chunks),
            duration_seconds=time.monotonic() - start, failures=failures,
        )

    def check_docker_build(self, timeout_seconds: float = 180.0) -> DockerBuildReport:
        """
        Versucht einen echten `docker build` des Projekts, falls ein Dockerfile existiert
        und `docker` lokal verfügbar ist – ein generiertes Dockerfile, das nie tatsächlich
        baut, bringt ein Projekt nicht näher an ein echtes Deployment. Baut NIE `docker run`
        oder gar einen echten Deploy aus – nur die Build-Fähigkeit wird geprüft. Das
        tatsächliche lokale Deployment (Docker Compose bzw. `docker run`) übernimmt bei Bedarf
        core/deployment.py, manuell ausgelöst über `/deploy` – bewusst getrennt von dieser
        automatischen Verifikationsprüfung, da eine echte Container-Ausführung Ports belegt
        und einen laufenden Prozess startet, eine reine Build-Prüfung dagegen nicht.
        """
        dockerfile = self.project_dir / "Dockerfile"
        if not dockerfile.exists():
            return DockerBuildReport(attempted=False, success=True, output="", reason_skipped="Kein Dockerfile im Projekt gefunden.")

        if shutil.which("docker") is None:
            return DockerBuildReport(attempted=False, success=True, output="", reason_skipped="Docker ist auf diesem System nicht installiert/verfügbar.")

        tag = f"ai-team-verify-{self.project_dir.name.lower()}"
        result = CodeSandbox.run_command(
            ["docker", "build", "-t", tag, "."],
            cwd=self.project_dir,
            timeout_seconds=timeout_seconds,
        )
        output = (result.stdout + result.stderr).strip()[-2000:]
        return DockerBuildReport(attempted=True, success=result.exit_code == 0, output=output)

    def check_dependency_vulnerabilities(self, timeout_seconds: float = 120.0) -> list[DependencyAuditReport]:
        reports: list[DependencyAuditReport] = []
        req_file = self._requirements_file()
        if req_file:
            reports.append(self._audit_python_dependencies(req_file, timeout_seconds))
        for node_dir in self._find_node_projects():
            reports.append(self._audit_node_dependencies(node_dir, timeout_seconds))
        if self._has_rust_project():
            reports.append(self._audit_rust_dependencies(timeout_seconds))
        if self._has_go_project():
            reports.append(self._audit_go_dependencies(timeout_seconds))
        return reports

    def _audit_rust_dependencies(self, timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("cargo") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="cargo-audit",
                reason_skipped="`cargo` ist auf diesem System nicht installiert/verfügbar.",
            )
        result = CodeSandbox.run_command(["cargo", "audit", "--json"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        if result.exit_code != 0 and "not found" in (result.stderr or "").lower():
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="cargo-audit",
                reason_skipped="`cargo-audit` ist nicht installiert (`cargo install cargo-audit`).",
            )
        return DependencyAuditReport(attempted=True, vulnerable=result.exit_code != 0, tool="cargo-audit")

    def _audit_go_dependencies(self, timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("govulncheck") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="govulncheck",
                reason_skipped="`govulncheck` ist auf diesem System nicht installiert (`go install golang.org/x/vuln/cmd/govulncheck@latest`).",
            )
        result = CodeSandbox.run_command(["govulncheck", "./..."], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return DependencyAuditReport(attempted=True, vulnerable=result.exit_code != 0, tool="govulncheck")

    def check_sast(self, timeout_seconds: float = 60.0) -> list[SastReport]:
        reports: list[SastReport] = []
        if self._has_python_files():
            reports.append(self._sast_python(timeout_seconds))
        return reports

    def _sast_python(self, timeout_seconds: float) -> SastReport:
        if shutil.which("bandit") is None:
            return SastReport(
                attempted=False, vulnerable=False, tool="bandit",
                reason_skipped="`bandit` ist auf diesem System nicht installiert/verfügbar (`pip install bandit`).",
            )
        # -x nimmt eine kommagetrennte Liste von Pfaden entgegen (kein wiederholbares Flag
        # wie ruffs --extend-exclude) – dieselben Build-/Umgebungs-Artefakte wie bei jedem
        # anderen Check (_IGNORED_DIRS) werden ausgeschlossen, keine vom Team geschriebenen
        # Projektdateien.
        exclude = ",".join(str(self.project_dir / d) for d in sorted(_IGNORED_DIRS))
        command = ["bandit", "-r", str(self.project_dir), "-f", "json", "-x", exclude]
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_bandit_result(result)

    def _parse_bandit_result(self, result: ExecutionResult) -> SastReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return SastReport(
                attempted=False, vulnerable=False, tool="bandit",
                reason_skipped=f"bandit lieferte kein gültiges Ergebnis: {tail}",
            )

        findings: list[SastFinding] = []
        for entry in data.get("results", []):
            raw_path = entry.get("filename", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            findings.append(SastFinding(
                file_path=rel,
                line_number=entry.get("line_number", 0),
                message=entry.get("issue_text", ""),
                rule=entry.get("test_id") or "",
                severity=entry.get("issue_severity", ""),
            ))
        return SastReport(attempted=True, vulnerable=len(findings) > 0, tool="bandit", findings=findings)

    def check_licenses(self, timeout_seconds: float = 60.0) -> list[LicenseAuditReport]:
        reports: list[LicenseAuditReport] = []
        if self._requirements_file():
            reports.append(self._license_audit_python(timeout_seconds))
        return reports

    def _license_audit_python(self, timeout_seconds: float) -> LicenseAuditReport:
        if shutil.which("pip-licenses") is None:
            return LicenseAuditReport(
                attempted=False, has_copyleft_risk=False, tool="pip-licenses",
                reason_skipped="`pip-licenses` ist auf diesem System nicht installiert/verfügbar (`pip install pip-licenses`).",
            )
        # pip-licenses liest Metadaten der TATSÄCHLICH installierten Pakete (kein Netzwerk,
        # anders als pip-audit) - braucht daher gezielt die isolierte Projekt-venv aus
        # ensure_environment() statt der Framework-eigenen Umgebung, in der das Tool selbst
        # installiert ist. --python zeigt auf den Ziel-Interpreter, dessen Pakete geprüft
        # werden sollen (fällt wie überall sonst auf den System-Interpreter zurück, falls die
        # venv noch nicht existiert - siehe _resolve_python()).
        command = ["pip-licenses", "--python", self._resolve_python(), "--format=json"]
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_pip_licenses_result(result)

    def _parse_pip_licenses_result(self, result: ExecutionResult) -> LicenseAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LicenseAuditReport(
                attempted=False, has_copyleft_risk=False, tool="pip-licenses",
                reason_skipped=f"pip-licenses lieferte kein gültiges Ergebnis: {tail}",
            )

        findings: list[LicenseFinding] = []
        for entry in data:
            license_str = entry.get("License", "") or ""
            findings.append(LicenseFinding(
                package=entry.get("Name", "?"),
                version=entry.get("Version", "?"),
                license=license_str,
                copyleft=_is_copyleft_license(license_str),
            ))
        return LicenseAuditReport(
            attempted=True, has_copyleft_risk=any(f.copyleft for f in findings),
            tool="pip-licenses", findings=findings,
        )

    def check_lint(self, timeout_seconds: float = 60.0) -> list[LintReport]:
        reports: list[LintReport] = []
        if self._has_python_files():
            reports.append(self._lint_python(timeout_seconds))
        for node_dir in self._find_node_projects():
            eslint_report = self._lint_node_eslint(node_dir, timeout_seconds)
            if eslint_report is not None:
                reports.append(eslint_report)
            tsc_report = self._typecheck_node_tsc(node_dir, timeout_seconds)
            if tsc_report is not None:
                reports.append(tsc_report)
        if self._has_rust_project():
            rust_lint = self._lint_rust(timeout_seconds)
            if rust_lint is not None:
                reports.append(rust_lint)
        if self._has_go_project():
            go_lint = self._lint_go(timeout_seconds)
            if go_lint is not None:
                reports.append(go_lint)
        return reports

    def _lint_rust(self, timeout_seconds: float) -> LintReport | None:
        if shutil.which("cargo") is None:
            return LintReport(attempted=False, passed=True, tool="clippy", reason_skipped="`cargo` nicht verfügbar.")
        result = CodeSandbox.run_command(["cargo", "clippy", "--message-format=json"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return LintReport(attempted=True, passed=result.exit_code == 0, tool="clippy")

    def _lint_go(self, timeout_seconds: float) -> LintReport | None:
        if shutil.which("go") is None:
            return LintReport(attempted=False, passed=True, tool="go vet", reason_skipped="`go` nicht verfügbar.")
        result = CodeSandbox.run_command(["go", "vet", "./..."], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return LintReport(attempted=True, passed=result.exit_code == 0, tool="go vet")

    def _audit_python_dependencies(self, req_file: Path, timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("pip-audit") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="pip-audit",
                reason_skipped="`pip-audit` ist auf diesem System nicht installiert/verfügbar "
                               "(`pip install pip-audit`).",
            )
        # `-r <requirements.txt>` löst Versionen direkt aus der Datei auf – braucht KEINE
        # lokale Installation der Pakete, funktioniert also unabhängig von der isolierten
        # venv (die für ein frisches Projekt evtl. noch gar nicht existiert).
        result = CodeSandbox.run_command(
            ["pip-audit", "-r", str(req_file), "-f", "json"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_pip_audit_result(result)

    def _parse_pip_audit_result(self, result: ExecutionResult) -> DependencyAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="pip-audit",
                reason_skipped=f"pip-audit lieferte kein gültiges Ergebnis (z. B. keine "
                               f"Netzwerkverbindung zur Advisory-Datenbank): {tail}",
            )

        vulnerabilities = [
            DependencyVulnerability(
                package=dep.get("name", "?"),
                version=dep.get("version", "?"),
                vulnerability_id=vuln.get("id", "?"),
                description=(vuln.get("description") or "").strip()[:300],
                fix_versions=list(vuln.get("fix_versions") or []),
            )
            for dep in data.get("dependencies", [])
            for vuln in dep.get("vulns", [])
        ]
        return DependencyAuditReport(
            attempted=True, vulnerable=len(vulnerabilities) > 0, tool="pip-audit",
            vulnerabilities=vulnerabilities,
        )

    def _audit_node_dependencies(self, node_dir: Path, timeout_seconds: float) -> DependencyAuditReport:
        rel = self._relative_label(node_dir)
        if shutil.which("npm") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm` ist auf diesem System nicht installiert/verfügbar ({rel}).",
            )
        if not (node_dir / "package-lock.json").exists():
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"Keine package-lock.json ({rel}) – `npm audit` benötigt eine Lockfile "
                               f"(wird normalerweise von ensure_environment() angelegt).",
            )

        result = CodeSandbox.run_command(
            ["npm", "audit", "--json"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_npm_audit_result(result, rel)

    def _parse_npm_audit_result(self, result: ExecutionResult, label: str) -> DependencyAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm audit` ({label}) lieferte kein gültiges Ergebnis: {tail}",
            )

        # `npm audit` meldet einen technischen Fehlschlag (z. B. Registry nicht erreichbar)
        # als {"error": {...}} OHNE "vulnerabilities"-Schlüssel – das darf NIE stillschweigend
        # als "keine Schwachstellen" durchgehen.
        if "error" in data and "vulnerabilities" not in data:
            error_detail = json.dumps(data.get("error", {}))[:500]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm audit` ({label}) meldete einen Fehler statt eines Scan-Ergebnisses: {error_detail}",
            )

        vulnerabilities: list[DependencyVulnerability] = []
        for pkg_name, pkg_info in data.get("vulnerabilities", {}).items():
            for via in pkg_info.get("via", []):
                if not isinstance(via, dict):
                    continue  # String-Eintrag = Verweis auf eine andere betroffene Abhängigkeit, keine eigene Advisory
                vuln_id = via.get("url", "").rsplit("/", 1)[-1] or via.get("title", "?")
                vulnerabilities.append(DependencyVulnerability(
                    package=pkg_name,
                    version=pkg_info.get("range", "?"),
                    vulnerability_id=vuln_id,
                    description=(via.get("title") or "").strip()[:300],
                    severity=via.get("severity", ""),
                ))
        total = data.get("metadata", {}).get("vulnerabilities", {}).get("total", len(vulnerabilities))
        return DependencyAuditReport(
            attempted=True, vulnerable=total > 0, tool="npm audit", vulnerabilities=vulnerabilities,
        )


    def _has_python_files(self) -> bool:
        return any(
            f for f in self.project_dir.rglob("*.py")
            if not any(part in _IGNORED_DIRS for part in f.parts)
        )

    def _lint_python(self, timeout_seconds: float) -> LintReport:
        if shutil.which("ruff") is None:
            return LintReport(
                attempted=False, passed=True, tool="ruff",
                reason_skipped="`ruff` ist auf diesem System nicht installiert/verfügbar (`pip install ruff`).",
            )
        # --isolated: ignoriert JEDE gefundene Konfigurationsdatei (auch die eigene
        # ruff.toml des Frameworks, falls das Projekt innerhalb des Repos liegt) und nutzt
        # ruffs neutrale Standardregeln – die eigenen, für den Framework-Code kuratierten
        # Regeln (z. B. E501-Ausnahme für deutschsprachige Docstrings) sollen einem
        # beliebigen generierten Projekt nicht aufgezwungen werden.
        command = ["ruff", "check", str(self.project_dir), "--isolated", "--output-format=json"]
        command += [f"--extend-exclude={d}" for d in sorted(_IGNORED_DIRS)]
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_ruff_result(result)

    def _parse_ruff_result(self, result: ExecutionResult) -> LintReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="ruff",
                reason_skipped=f"ruff lieferte kein gültiges Ergebnis: {tail}",
            )

        issues: list[LintIssue] = []
        for entry in data:
            raw_path = entry.get("filename", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            issues.append(LintIssue(
                file_path=rel,
                line_number=entry.get("location", {}).get("row", 0),
                message=entry.get("message", ""),
                rule=entry.get("code") or "",
            ))
        return LintReport(attempted=True, passed=len(issues) == 0, tool="ruff", issues=issues)

    def _node_bin(self, node_dir: Path, name: str) -> Path | None:
        """Löst ein lokal in node_modules/.bin installiertes Node-Tool auf (kein globales npx-
        Auto-Install, kein interaktiver Prompt) – nur, wenn das Projekt es selbst installiert hat."""
        candidates = [node_dir / "node_modules" / ".bin" / name]
        if sys.platform == "win32":
            candidates.append(node_dir / "node_modules" / ".bin" / f"{name}.cmd")
        return next((c for c in candidates if c.exists()), None)

    def _lint_node_eslint(self, node_dir: Path, timeout_seconds: float) -> LintReport | None:
        if not any((node_dir / name).exists() for name in _ESLINT_CONFIG_NAMES):
            return None  # Projekt nutzt erkennbar kein ESLint - keine ungefragte Meinungsänderung
        rel = self._relative_label(node_dir)
        eslint_bin = self._node_bin(node_dir, "eslint")
        if eslint_bin is None:
            return LintReport(
                attempted=False, passed=True, tool="eslint",
                reason_skipped=f"ESLint-Konfiguration gefunden, aber ESLint nicht in node_modules "
                               f"installiert ({rel}).",
            )
        result = CodeSandbox.run_command(
            [str(eslint_bin), ".", "--format=json"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_eslint_result(result, node_dir)

    def _parse_eslint_result(self, result: ExecutionResult, node_dir: Path) -> LintReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="eslint",
                reason_skipped=f"ESLint lieferte kein gültiges Ergebnis: {tail}",
            )

        issues: list[LintIssue] = []
        for file_entry in data:
            raw_path = file_entry.get("filePath", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            for msg in file_entry.get("messages", []):
                if msg.get("severity", 0) < 2:
                    continue  # severity 1 = Warnung, nur echte Fehler (2) zählen als "nicht bestanden"
                issues.append(LintIssue(
                    file_path=rel, line_number=msg.get("line", 0),
                    message=msg.get("message", ""), rule=msg.get("ruleId") or "",
                ))
        return LintReport(attempted=True, passed=len(issues) == 0, tool="eslint", issues=issues)

    def _typecheck_node_tsc(self, node_dir: Path, timeout_seconds: float) -> LintReport | None:
        if not (node_dir / "tsconfig.json").exists():
            return None  # Projekt nutzt erkennbar kein TypeScript - nichts zu typprüfen
        rel = self._relative_label(node_dir)
        tsc_bin = self._node_bin(node_dir, "tsc")
        if tsc_bin is None:
            return LintReport(
                attempted=False, passed=True, tool="tsc",
                reason_skipped=f"tsconfig.json gefunden, aber TypeScript nicht in node_modules "
                               f"installiert ({rel}).",
            )
        result = CodeSandbox.run_command(
            [str(tsc_bin), "--noEmit", "--pretty", "false"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_tsc_result(result, node_dir)

    def _parse_tsc_result(self, result: ExecutionResult, node_dir: Path) -> LintReport:
        # tsc hat kein natives JSON-Format (anders als ruff/ESLint) - ein leerer Output bei
        # exit_code 0 bedeutet "keine Fehler", jedes andere Ergebnis wird per _TSC_ERROR_PATTERN
        # geparst. Kein strukturiertes Muster gefunden trotz Fehlschlag -> generischer Fallback,
        # analog zu den anderen best-effort geparsten Ausgaben (z. B. _parse_node_failures).
        output = f"{result.stdout}\n{result.stderr}"
        matches = list(_TSC_ERROR_PATTERN.finditer(output))

        if not matches:
            if result.exit_code == 0:
                return LintReport(attempted=True, passed=True, tool="tsc")
            tail = output.strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="tsc",
                reason_skipped=f"tsc lieferte kein auswertbares Ergebnis (exit_code={result.exit_code}): {tail}",
            )

        issues: list[LintIssue] = []
        for m in matches:
            raw_path, line_no, _col, _level, code, message = m.groups()
            path = Path(raw_path)
            try:
                abs_path = path if path.is_absolute() else (node_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            issues.append(LintIssue(file_path=rel, line_number=int(line_no), message=message.strip(), rule=code))

        return LintReport(attempted=True, passed=False, tool="tsc", issues=issues)

    def check_coverage(self, timeout_seconds: float = 60.0) -> CoverageReport:
        """
        Misst die echte Python-Testabdeckung per `pytest-cov`, WENN das Projekt es bereits
        selbst als Abhängigkeit mitbringt (siehe CoverageReport-Docstring) UND echte
        Python-Testdateien existieren. Bewusst kein separater Node/Coverage-Zweig - anders als
        Testausführung/Lint gibt es kein annähernd einheitliches Coverage-Tool über die
        verschiedenen Node-Test-Runner hinweg (Jest/Vitest/Mocha je eigenes Format).
        """
        if not self._find_python_test_files():
            return CoverageReport(attempted=False, reason_skipped="Keine Python-Testdateien gefunden.")

        python_exe = self._resolve_python()
        cov_check = CodeSandbox.run_command(
            [python_exe, "-c", "import pytest_cov"], cwd=self.project_dir, timeout_seconds=10.0,
        )
        if cov_check.exit_code != 0:
            return CoverageReport(
                attempted=False,
                reason_skipped="`pytest-cov` ist in diesem Projekt nicht installiert - das "
                               "Framework fügt es nicht selbst nachträglich hinzu.",
            )

        report_file = self.project_dir / "coverage_report.json"
        try:
            result = CodeSandbox.run_command(
                [python_exe, "-m", "pytest", "-q", "--tb=no",
                 f"--cov={self.project_dir}", f"--cov-report=json:{report_file}"],
                cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
            if not report_file.exists():
                tail = (result.stdout + result.stderr).strip()[-500:]
                return CoverageReport(attempted=False, reason_skipped=f"pytest-cov lieferte kein Ergebnis: {tail}")
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                return CoverageReport(attempted=False, reason_skipped=f"Coverage-JSON nicht lesbar: {e}")
            percent = round(data.get("totals", {}).get("percent_covered", 0.0), 1)
            return CoverageReport(attempted=True, percent=percent)
        finally:
            report_file.unlink(missing_ok=True)

    def _run_pytest_or_unittest(self, python_exe: str, timeout_seconds: float) -> ExecutionResult:
        pytest_check = CodeSandbox.run_command([python_exe, "-c", "import pytest"], cwd=self.project_dir, timeout_seconds=10.0)
        if pytest_check.exit_code == 0:
            return CodeSandbox.run_command(
                [python_exe, "-m", "pytest", "-q", "--tb=short", str(self.project_dir)],
                cwd=self.project_dir, timeout_seconds=timeout_seconds,
            )
        return CodeSandbox.run_command(
            [python_exe, "-m", "unittest", "discover", "-s", str(self.project_dir), "-p", "test_*.py"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )

    def _parse_python_failures(self, exec_result: ExecutionResult) -> list[TestFailure]:
        """Parst echte pytest-/unittest-Ausgaben – keine Schlagwortsuche in Freitext."""
        output = f"{exec_result.stdout}\n{exec_result.stderr}"
        failures: dict[str, TestFailure] = {}

        # pytest-Format: "FAILED tests/test_x.py::test_foo - AssertionError: ..."
        for m in re.finditer(r'^FAILED (\S+)(?:\s+-\s+(.*))?$', output, re.MULTILINE):
            test_id = m.group(1)
            failures[test_id] = TestFailure(test_id=test_id, message=(m.group(2) or "").strip())

        # unittest-Format: "FAIL: test_foo (module.TestCase)" / "ERROR: test_foo (module.TestCase)"
        for m in re.finditer(r'^(?:FAIL|ERROR): (.+)$', output, re.MULTILINE):
            test_id = m.group(1).strip()
            failures.setdefault(test_id, TestFailure(test_id=test_id, message=""))

        # Tracebacks: welche Projektdateien tauchen tatsächlich auf? (site-packages/venv ausgeschlossen)
        # Zwei Formate müssen erkannt werden:
        #   1. Klassischer Python-/unittest-Traceback:  File "pfad/datei.py", line 42
        #   2. pytest --tb=short:                        pfad/datei.py:42: in test_foo
        raw_paths = re.findall(r'File "([^"]+)", line \d+', output)
        raw_paths += re.findall(r'^([^\s:][^\n:]*?\.py):\d+: in ', output, re.MULTILINE)

        implicated_files: list[str] = []
        for fp in raw_paths:
            path = Path(fp)
            if any(part in (VENV_DIRNAME, ".venv", "venv", "site-packages") for part in path.parts):
                continue
            try:
                abs_path = path if path.is_absolute() else (self.project_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                continue
            if rel not in implicated_files:
                implicated_files.append(rel)

        if not failures:
            # Kein strukturiertes FAILED/FAIL/ERROR-Muster erkannt (z.B. Sammel-/Importfehler
            # beim Einsammeln der Tests) – trotzdem als generischer Fehlschlag mit realem Output melden.
            failures["<Testlauf>"] = TestFailure(test_id="<Testlauf>", message=output.strip()[-800:])

        for failure in failures.values():
            failure.files = implicated_files

        return list(failures.values())

    def _parse_node_failures(self, exec_result: ExecutionResult, node_dir: Path) -> list[TestFailure]:
        """
        Best-effort-Parsing echter `npm test`-Ausgaben – anders als bei pytest/unittest gibt
        es kein einheitliches Node-Test-Ausgabeformat (Jest, Vitest, Mocha, ... unterscheiden
        sich). Erkennt das verbreitete "FAIL <datei>"-Muster (Jest/Vitest) sowie Dateipfade
        aus Stack-Traces; liefert sonst denselben generischen Fallback wie bei unparsbarer
        Python-Ausgabe (siehe _parse_python_failures).
        """
        output = f"{exec_result.stdout}\n{exec_result.stderr}"
        failures: dict[str, TestFailure] = {}

        for m in _NODE_FAIL_FILE_PATTERN.finditer(output):
            test_id = m.group(1)
            failures.setdefault(test_id, TestFailure(test_id=test_id, message=""))

        implicated_files: list[str] = []
        for fp in _NODE_STACK_FILE_PATTERN.findall(output):
            path = Path(fp)
            if "node_modules" in path.parts:
                continue
            try:
                abs_path = path if path.is_absolute() else (node_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                continue
            if rel not in implicated_files:
                implicated_files.append(rel)

        if not failures:
            failures["<npm test>"] = TestFailure(test_id="<npm test>", message=output.strip()[-800:])

        for failure in failures.values():
            failure.files = implicated_files

        return list(failures.values())

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def check_runtime_smoke(self, timeout_seconds: float = 6.0) -> RuntimeSmokeReport:
        """
        Prüft durch einen kurzen Teststart im Subprozess, ob die generierte App tatsächlich
        lauffähig ist (Runtime-Smoke-Test):
        - Web-/API-Apps (FastAPI/Flask/uvicorn/http.server): Start auf freiem lokalem Port,
          Polling von GET / oder GET /health, ob der Server antwortet.
        - CLI-Skripte (mit argparse/click): Start mit `--help`, ob das Skript ohne Syntax-/
          Importfehler durchläuft.
        - Node.js-Server (index.js/server.js/app.js): Syntax-/Startprüfung per Node.
        """
        python_exe = self._resolve_python()

        # 1. Suche nach Python-Einstiegspunkten
        for entry_name in ("main.py", "app.py", "server.py", "api.py"):
            entry_file = self.project_dir / entry_name
            if entry_file.exists():
                try:
                    content = entry_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                is_web = any(kw in content for kw in ("FastAPI", "uvicorn", "Flask", "aiohttp", "http.server", "HTTPServer"))
                if is_web:
                    port = self._find_free_port()
                    # Bugfix (beim Bau des Lastentest-Checks entdeckt): CodeSandbox.safe_environment()
                    # existierte nie - dieser Zweig wäre bei JEDER erkannten Web-App mit
                    # AttributeError gecrasht. Blieb unbemerkt, weil kein Test den http_api-Zweig je
                    # mit einem echten Popen-Aufruf durchlaufen hat (siehe tests/test_verifier_smoke.py:
                    # nur cli_script/node_server sind dort real getestet). Korrekt ist
                    # CodeSandbox._restricted_env() - dieselbe Secret-Filterung, die run_command()
                    # bereits für jeden Subprozess nutzt.
                    env = {**CodeSandbox._restricted_env(), "PORT": str(port), "UVICORN_PORT": str(port)}
                    cmd = [python_exe, str(entry_file)]
                    if "uvicorn" in content and ("app = FastAPI" in content or "app =" in content):
                        module_name = entry_name[:-3]
                        cmd = [python_exe, "-m", "uvicorn", f"{module_name}:app", "--port", str(port), "--host", "127.0.0.1"]

                    proc = None
                    try:
                        proc = subprocess.Popen(
                            cmd, cwd=self.project_dir, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        )
                        start_time = time.monotonic()
                        status_code = None
                        while time.monotonic() - start_time < timeout_seconds:
                            if proc.poll() is not None:
                                stdout, stderr = proc.communicate(timeout=1.0)
                                return RuntimeSmokeReport(
                                    attempted=True, passed=False, entrypoint=entry_name,
                                    app_type="http_api", output=(stderr or stdout).strip()[-500:],
                                )
                            try:
                                req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"User-Agent": "AI-Team-Smoke-Test"})
                                with urllib.request.urlopen(req, timeout=1.0) as resp:
                                    status_code = resp.status
                                    break
                            except urllib.error.HTTPError as e:
                                # HTTP 404/401/403/etc. bedeutet: Server LÄUFT und antwortet per HTTP
                                status_code = e.code
                                break
                            except (urllib.error.URLError, ConnectionError, OSError):
                                time.sleep(0.3)

                        if status_code is not None:
                            return RuntimeSmokeReport(
                                attempted=True, passed=True, entrypoint=entry_name,
                                app_type="http_api", status_code=status_code,
                            )
                        else:
                            return RuntimeSmokeReport(
                                attempted=True, passed=False, entrypoint=entry_name,
                                app_type="http_api", output="Timeout: HTTP-Server antwortete nicht innerhalb des Timeouts.",
                            )
                    finally:
                        if proc and proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=2.0)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                else:
                    # CLI / Skript: Teststart mit --help
                    res = CodeSandbox.run_command([python_exe, str(entry_file), "--help"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
                    if res.exit_code == 0 or "usage:" in (res.stdout + res.stderr).lower() or "--help" in (res.stdout + res.stderr):
                        return RuntimeSmokeReport(attempted=True, passed=True, entrypoint=entry_name, app_type="cli_script")
                    elif res.exit_code != 0 and not res.timed_out:
                        return RuntimeSmokeReport(
                            attempted=True, passed=False, entrypoint=entry_name,
                            app_type="cli_script", output=(res.stderr or res.stdout).strip()[-500:],
                        )

        # 2. Suche nach Node-Einstiegspunkten
        for entry_name in ("index.js", "server.js", "app.js"):
            entry_file = self.project_dir / entry_name
            if entry_file.exists():
                res = CodeSandbox.run_command(["node", "-c", str(entry_file)], cwd=self.project_dir, timeout_seconds=5.0)
                if res.exit_code == 0:
                    return RuntimeSmokeReport(attempted=True, passed=True, entrypoint=entry_name, app_type="node_server")
                else:
                    return RuntimeSmokeReport(
                        attempted=True, passed=False, entrypoint=entry_name,
                        app_type="node_server", output=(res.stderr or res.stdout).strip()[-500:],
                    )

        return RuntimeSmokeReport(attempted=False, reason_skipped="Kein ausführbarer Einstiegspunkt (main.py, app.py, server.js) gefunden.")

    def check_browser_ui(self, timeout_seconds: float = 8.0):
        """
        Prüft Frontend-/Web-Projekte per Headless-Browser oder statischer DOM-Validierung
        auf fehlende Assets, JavaScript-Fehler und Rendering-Probleme.
        """
        from core.browser_verifier import BrowserVerifier
        verifier = BrowserVerifier(self.project_dir)
        return verifier.verify_frontend(timeout_seconds=timeout_seconds)

    def check_accessibility(self, timeout_seconds: float = 10.0):
        """
        Prüft Frontend-/Web-Projekte per echtem axe-core-Scan (WCAG 2.x) auf konkrete,
        geparste Barrierefreiheits-Verstöße – ersetzt die bisherige rein LLM-basierte
        Einschätzung des accessibility-Agenten. Dünne Delegation an BrowserVerifier, exakt wie
        check_browser_ui().
        """
        from core.browser_verifier import BrowserVerifier
        verifier = BrowserVerifier(self.project_dir)
        return verifier.verify_accessibility(timeout_seconds=timeout_seconds)

    def check_load_test(self, load_seconds: float = 5.0, timeout_seconds: float = 60.0) -> PerfCheckReport:
        """
        Führt einen vom performance-Agenten geschriebenen Lastentest ECHT aus (bisher wurden
        die Skripte nie ausgeführt). Sucht ausschließlich unter LOAD_TEST_DIRNAME
        (tests/load/) - `locustfile.py` (echter Standard-Dateiname von Locust) hat Vorrang vor
        k6-Skripten (*.js), falls beide vorhanden sind. Aktuell nur für Python-Web-Apps (siehe
        _start_python_web_app) - dieselbe Einstiegspunkt-Erkennung wie check_runtime_smoke(),
        hier bewusst separat gehalten statt geteilt, da der Lastentest den Prozess über die
        gesamte Testdauer am Leben halten muss statt ihn nur kurz anzupingen.
        """
        load_dir = self.project_dir / LOAD_TEST_DIRNAME
        locustfile = load_dir / "locustfile.py"
        k6_scripts = sorted(load_dir.glob("*.js")) if load_dir.exists() else []

        if not locustfile.exists() and not k6_scripts:
            return PerfCheckReport(
                attempted=False,
                reason_skipped=f"Kein Lastentest-Skript unter {LOAD_TEST_DIRNAME}/ gefunden (locustfile.py oder *.js).",
            )

        tool = "locust" if locustfile.exists() else "k6"
        script = locustfile if tool == "locust" else k6_scripts[0]
        if shutil.which(tool) is None:
            return PerfCheckReport(
                attempted=False, tool=tool, script=self._relative_label(script.parent) + "/" + script.name,
                reason_skipped=f"`{tool}` ist auf diesem System nicht installiert/verfügbar.",
            )

        started = self._start_python_web_app(timeout_seconds)
        if started is None:
            return PerfCheckReport(
                attempted=False, tool=tool, script=self._relative_label(script.parent) + "/" + script.name,
                reason_skipped="Kein startfähiger Python-Web-Einstiegspunkt gefunden oder die App startet nicht - Lastentest übersprungen.",
            )
        proc, port = started
        try:
            if tool == "locust":
                return self._run_locust_load_test(locustfile, port, load_seconds, timeout_seconds)
            return self._run_k6_load_test(k6_scripts[0], port, load_seconds, timeout_seconds)
        finally:
            self._terminate_process(proc)

    def _start_python_web_app(self, timeout_seconds: float) -> tuple[subprocess.Popen, int] | None:
        """
        Startet einen gefundenen Python-Web-Einstiegspunkt (main.py/app.py/server.py/api.py mit
        FastAPI/uvicorn/Flask/aiohttp) im Subprozess auf einem freien Port und wartet, bis er
        antwortet - dieselbe Erkennung wie im http_api-Zweig von check_runtime_smoke(). Gibt
        (proc, port) zurück, sobald die App antwortet, sonst None (kein Web-Einstiegspunkt
        gefunden, oder die App startet nicht rechtzeitig). Der Aufrufer ist für
        _terminate_process(proc) verantwortlich.
        """
        python_exe = self._resolve_python()
        for entry_name in ("main.py", "app.py", "server.py", "api.py"):
            entry_file = self.project_dir / entry_name
            if not entry_file.exists():
                continue
            try:
                content = entry_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if not any(kw in content for kw in ("FastAPI", "uvicorn", "Flask", "aiohttp", "http.server", "HTTPServer")):
                continue

            port = self._find_free_port()
            env = {**CodeSandbox._restricted_env(), "PORT": str(port), "UVICORN_PORT": str(port)}
            cmd = [python_exe, str(entry_file)]
            if "uvicorn" in content and "app =" in content:
                module_name = entry_name[:-3]
                cmd = [python_exe, "-m", "uvicorn", f"{module_name}:app", "--port", str(port), "--host", "127.0.0.1"]

            proc = subprocess.Popen(
                cmd, cwd=self.project_dir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout_seconds:
                if proc.poll() is not None:
                    return None  # abgestürzt, bevor es antwortete
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"User-Agent": "AI-Team-Load-Test"})
                    with urllib.request.urlopen(req, timeout=1.0):
                        pass
                    return proc, port
                except urllib.error.HTTPError:
                    return proc, port  # antwortet per HTTP (auch 404/401/... = läuft)
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.3)
            self._terminate_process(proc)
            return None
        return None

    def _terminate_process(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _run_locust_load_test(self, locustfile: Path, port: int, load_seconds: float, timeout_seconds: float) -> PerfCheckReport:
        script_label = self._relative_label(locustfile.parent) + "/" + locustfile.name
        with tempfile.TemporaryDirectory() as tmp:
            csv_prefix = str(Path(tmp) / "loadtest")
            command = [
                "locust", "-f", str(locustfile), "--headless",
                "-u", "3", "-r", "3", "-t", f"{int(load_seconds)}s",
                "--host", f"http://127.0.0.1:{port}",
                "--csv", csv_prefix,
            ]
            result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
            stats_file = Path(f"{csv_prefix}_stats.csv")
            if not stats_file.exists():
                tail = (result.stdout + result.stderr).strip()[-800:]
                return PerfCheckReport(
                    attempted=False, tool="locust", script=script_label,
                    reason_skipped=f"locust lieferte kein auswertbares Ergebnis: {tail}",
                )
            return self._parse_locust_stats(stats_file, script_label)

    def _parse_locust_stats(self, stats_file: Path, script_label: str) -> PerfCheckReport:
        """
        Parst die von `locust --csv` geschriebene `<prefix>_stats.csv` per csv.DictReader
        (liest nach Spalten-NAME, nicht nach Position - robust gegen Spaltenreihenfolge-
        Unterschiede zwischen Locust-Versionen). Die "Aggregated"-Zeile fasst alle
        definierten Requests des Laufs zusammen.
        """
        try:
            with stats_file.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError as e:
            return PerfCheckReport(attempted=False, tool="locust", script=script_label, reason_skipped=f"locust-CSV nicht lesbar: {e}")

        aggregated = next((r for r in rows if r.get("Name") == "Aggregated"), None)
        if aggregated is None:
            return PerfCheckReport(
                attempted=False, tool="locust", script=script_label,
                reason_skipped="locust-CSV enthält keine 'Aggregated'-Zeile - kein auswertbares Ergebnis.",
            )

        total = int(_csv_float(aggregated, "Request Count") or 0)
        failed = int(_csv_float(aggregated, "Failure Count") or 0)
        p95 = _csv_float(aggregated, "95%")
        return PerfCheckReport(
            attempted=True, tool="locust", script=script_label, passed=(failed == 0),
            total_requests=total, failed_requests=failed, p95_ms=p95,
        )

    def _run_k6_load_test(self, script: Path, port: int, load_seconds: float, timeout_seconds: float) -> PerfCheckReport:
        script_label = self._relative_label(script.parent) + "/" + script.name
        with tempfile.TemporaryDirectory() as tmp:
            summary_file = Path(tmp) / "summary.json"
            command = [
                "k6", "run", "--vus", "3", "--duration", f"{int(load_seconds)}s",
                "-e", f"BASE_URL=http://127.0.0.1:{port}",
                f"--summary-export={summary_file}", str(script),
            ]
            result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
            if not summary_file.exists():
                tail = (result.stdout + result.stderr).strip()[-800:]
                return PerfCheckReport(
                    attempted=False, tool="k6", script=script_label,
                    reason_skipped=f"k6 lieferte kein auswertbares Ergebnis: {tail}",
                )
            return self._parse_k6_summary(summary_file, script_label, result.exit_code)

    def _parse_k6_summary(self, summary_file: Path, script_label: str, exit_code: int) -> PerfCheckReport:
        """
        Parst die von `k6 run --summary-export=<datei>` geschriebene JSON-Zusammenfassung.
        Best effort: k6 hat das Summary-JSON-Format zwischen Versionen leicht verändert
        (Zahlen mal flach im Metrik-Objekt, mal unter einem "values"-Unterschlüssel) - beide
        Formen werden akzeptiert, kein Anspruch, jede k6-Version exakt zu kennen. Liefert das
        JSON keine der erwarteten Metriken, werden konservativ 0/None gemeldet statt zu
        crashen (dieselbe tolerante Grundhaltung wie beim Best-Effort-Parsing der Node-
        Testausgaben in _parse_node_failures).
        """
        try:
            data = json.loads(summary_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return PerfCheckReport(attempted=False, tool="k6", script=script_label, reason_skipped=f"k6-Summary-JSON nicht lesbar: {e}")

        metrics = data.get("metrics", {}) if isinstance(data, dict) else {}

        def _metric_value(name: str, field: str):
            entry = metrics.get(name)
            if not isinstance(entry, dict):
                return None
            values = entry.get("values", entry)
            return values.get(field) if isinstance(values, dict) else None

        total = _metric_value("http_reqs", "count")
        fail_rate = _metric_value("http_req_failed", "rate")
        p95 = _metric_value("http_req_duration", "p(95)")

        total_requests = int(total) if isinstance(total, (int, float)) else 0
        failed_requests = int(round(total_requests * fail_rate)) if isinstance(fail_rate, (int, float)) else 0
        return PerfCheckReport(
            attempted=True, tool="k6", script=script_label,
            passed=(exit_code == 0 and failed_requests == 0),
            total_requests=total_requests, failed_requests=failed_requests,
            p95_ms=float(p95) if isinstance(p95, (int, float)) else None,
        )


