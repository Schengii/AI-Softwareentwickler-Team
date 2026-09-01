"""
core/verifier/ – Echte Verifikation statt Keyword-Raten

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

---

Struktur-Refactoring (dieses Paket ersetzt das frühere monolithische core/verifier.py, keine
Verhaltensänderung): die Prüf-Logik ist nach fachlichen Verantwortlichkeiten in Mixins
aufgeteilt, die die ProjectVerifier-Klasse hier zusammensetzt:

- environment.py – EnvironmentMixin: isolierte venv/npm/cargo/go-Umgebung, Stack-Erkennung
- testrunner.py  – TestRunnerMixin: run_tests() + Fehlschlag-Parsing (Python/Node)
- security.py    – SecurityMixin: SAST (bandit), Dependency-Audit (pip-audit/npm audit/...), Lizenz-Audit
- lint.py        – LintMixin: ruff/ESLint/tsc/clippy/go vet
- coverage.py     – CoverageMixin: pytest-cov
- runtime.py     – RuntimeMixin: Docker-Build, Runtime-Smoke-Test, Browser-/A11y-Checks, Lastentest
- models.py      – gemeinsame Datenklassen (Reports) und Konstanten

Alle bisherigen Importpfade (`from core.verifier import ProjectVerifier, ...`) bleiben
unverändert nutzbar – siehe Re-Exports unten.
"""

import shutil  # noqa: F401 - re-exportiert für Tests, die core.verifier.shutil.which patchen (siehe unten)
import subprocess  # noqa: F401 - re-exportiert für Tests, die core.verifier.subprocess.Popen patchen
import urllib.request  # noqa: F401 - re-exportiert für Tests, die core.verifier.urllib.request.urlopen patchen

from core.code_sandbox import (
    CodeSandbox,  # noqa: F401 - re-exportiert für Tests, die core.verifier.CodeSandbox.run_command patchen
)
from core.verifier.completeness import CompletenessMixin
from core.verifier.coverage import CoverageMixin
from core.verifier.environment import EnvironmentMixin
from core.verifier.lint import LintMixin
from core.verifier.models import (
    LOAD_TEST_DIRNAME,
    VENV_DIRNAME,
    CompletenessIssue,
    CompletenessReport,
    CoverageReport,
    DependencyAuditReport,
    DependencyVulnerability,
    DockerBuildReport,
    LicenseAuditReport,
    LicenseFinding,
    LintIssue,
    LintReport,
    PerfCheckReport,
    RuntimeSmokeReport,
    SastFinding,
    SastReport,
    TestFailure,
    VerificationReport,
)
from core.verifier.runtime import RuntimeMixin
from core.verifier.security import SecurityMixin
from core.verifier.testrunner import TestRunnerMixin

__all__ = [
    "ProjectVerifier",
    "VerificationReport",
    "TestFailure",
    "DockerBuildReport",
    "DependencyVulnerability",
    "DependencyAuditReport",
    "SastFinding",
    "SastReport",
    "LicenseFinding",
    "LicenseAuditReport",
    "LintIssue",
    "LintReport",
    "CoverageReport",
    "RuntimeSmokeReport",
    "PerfCheckReport",
    "CompletenessIssue",
    "CompletenessReport",
    "VENV_DIRNAME",
    "LOAD_TEST_DIRNAME",
]


class ProjectVerifier(
    RuntimeMixin,
    CoverageMixin,
    LintMixin,
    SecurityMixin,
    TestRunnerMixin,
    CompletenessMixin,
    EnvironmentMixin,
):
    """Installiert Abhängigkeiten isoliert und führt die reale Testsuite eines Projekts aus."""
