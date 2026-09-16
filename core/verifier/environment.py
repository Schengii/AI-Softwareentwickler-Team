"""
core/verifier/environment.py – EnvironmentMixin: legt bei Bedarf eine isolierte virtuelle
Umgebung im Projekt an und installiert echte Abhängigkeiten (Python venv+pip, npm ci/install,
cargo, go) sowie die dafür nötige Stack-Erkennung (Node-Projekte, Rust/Go-Projekte).

Definiert außerdem __init__() der ProjectVerifier-Klasse (self.project_dir) – Grundlage,
auf der alle anderen Check-Mixins (testrunner, security, lint, coverage, runtime) aufbauen.
"""

import json
import re
import shutil
import sys
from pathlib import Path

from core.code_sandbox import CodeSandbox, ExecutionResult
from core.docker_sandbox import DockerSandbox
from core.manifest_guard import describe_toxic_dependencies, sanitize_requirements_file
from core.verifier.models import _IGNORED_DIRS, VENV_DIRNAME

# Team-Optimierung (NexusForge-Lauf, Schwachstelle 3): dieselbe Token-Grenze wie
# core/verifier/completeness.py._manifest_has_package() - erkennt "pytest-asyncio"/"anyio" auch
# als "pytest_asyncio" (Unterstrich statt Bindestrich) oder mit angehängtem Versions-Spezifizierer
# (z.B. "pytest-asyncio==0.21.0"), ohne z.B. "pytest-asyncioX" oder "not-anyio-related" fälschlich
# als bereits vorhanden zu werten.
_ASYNC_TEST_DEPENDENCY_TOKEN_RE = re.compile(r"(?<![a-z0-9.-])(pytest-asyncio|anyio)(?![a-z0-9.-])")


class EnvironmentMixin:
    """Installiert Abhängigkeiten isoliert und stellt die Stack-Erkennung für ein Projekt bereit."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()

    def _venv_python(self) -> Path:
        venv_dir = self.project_dir / VENV_DIRNAME
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _requirements_files(self) -> list[Path]:
        files = []
        # Dieselben Manifest-Namen, die core/manifest_guard.py bereits als gültige Python-
        # Requirements-Dateien anerkennt (_PYTHON_REQUIREMENTS_MANIFESTS) - vorher fehlten
        # requirements-test.txt/requirements-prod.txt hier, sodass ein Agent, der eine dieser
        # (vom Korruptions-Schutz bereits als legitim behandelten) Dateien anlegt, in der
        # Sandbox trotzdem NIE installiert worden wäre: dieselbe Dependency-Desynchronisation
        # wie beim ursprünglichen requirements-dev.txt-Fund, nur unter anderem Dateinamen.
        for name in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt", "requirements-prod.txt"):
            candidate = self.project_dir / name
            if candidate.exists() and candidate.stat().st_size > 0:
                files.append(candidate)
        return files

    def ensure_environment(self, timeout_seconds: float = 120.0) -> str:
        """
        Installiert echte Abhängigkeiten für JEDEN im Projekt gefundenen Stack:
        - Python: legt bei vorhandener requirements.txt/requirements-dev.txt eine isolierte venv an und
          installiert per pip (sowohl Produktiv- als auch Test-Abhängigkeiten).
        - Node: für jedes gefundene package.json mit "test"-Skript per `npm ci`
          (bei vorhandener package-lock.json, deterministisch) oder `npm install`.
        Gibt eine kombinierte Statuszeile zurück (leer, wenn nichts zu tun war, z.B.
        ein reines Textprojekt ohne requirements.txt/package.json).
        """
        logs: list[str] = []
        req_files = self._requirements_files()
        for req_file in req_files:
            logs.append(self._ensure_python_environment(req_file, timeout_seconds))
        # Team-Optimierung (echter Fund, `recurring-failure-event_relay`/
        # `recurring-failure-service_bookmark_monitor`-Tickets in memory/backlog.json): siehe
        # _ensure_pytest_available()-Docstring - nur relevant, wenn überhaupt eine venv angelegt
        # wurde (req_files nicht leer) UND echte pytest-Testdateien existieren, sonst unnötiger
        # zusätzlicher pip-Aufruf für Projekte ohne Python-Tests.
        if req_files and self._find_python_test_files():
            logs.append(self._ensure_pytest_available(timeout_seconds))
        pytest_ini_log = self._ensure_pytest_ini()
        if pytest_ini_log:
            logs.append(pytest_ini_log)
        async_manifest_log = self._ensure_async_test_manifest_entry()
        if async_manifest_log:
            logs.append(async_manifest_log)
        # Team-Optimierung (NexusForge-Lauf, Schwachstelle 1): vormals wurde
        # _ensure_node_environment() ausschließlich für _find_node_projects() (Projekte mit
        # "test"-Skript) aufgerufen. Ein reines Frontend (z.B. Vite/React) mit nur einem
        # "build"-Skript (_find_node_build_projects()) erhielt dadurch VOR dem Build kein
        # `npm install`/`npm ci` - RuntimeMixin.check_frontend_build() scheiterte dann mit
        # "keine node_modules erzeugt", obwohl das Projekt selbst fehlerfrei war. Die
        # Vereinigungsmenge (dedupliziert über den Verzeichnispfad) beider Suchen stellt sicher,
        # dass jedes Node-Projekt mit Build- ODER Test-Skript seine Abhängigkeiten vorab erhält.
        node_dirs = list(self._find_node_projects())
        for node_dir in self._find_node_build_projects():
            if node_dir not in node_dirs:
                node_dirs.append(node_dir)
        for node_dir in node_dirs:
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

    @staticmethod
    def _pip_status_line(req_file: Path, install_result: ExecutionResult, suffix: str = "") -> str:
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        tail = (install_result.stdout + install_result.stderr).strip()[-800:]
        return (
            f"{status} pip install -r {req_file.name} (exit_code={install_result.exit_code}){suffix}"
            + (f"\n{tail}" if install_result.exit_code != 0 else "")
        )

    def _ensure_python_environment(self, req_file: Path, timeout_seconds: float) -> str:
        # Letzte Verteidigungslinie vor pip: toxische Paket-Kollisionen (`jwt` neben `pyjwt`)
        # überschreiben sonst lautlos einen Namespace, obwohl pip exit_code=0 meldet.
        sanitize_note = ""
        if req_file.name.startswith("requirements"):
            try:
                toxic = sanitize_requirements_file(req_file)
                if toxic:
                    sanitize_note = describe_toxic_dependencies(req_file.name, toxic) + "\n"
            except OSError as e:
                sanitize_note = f"⚠️ Konnte {req_file.name} nicht auf toxische Paket-Kollisionen bereinigen: {e}\n"

        if DockerSandbox.is_active():
            # setup.py-/Build-Skripte der Pakete laufen im Container ohne Zugriff auf die Framework-.env
            # (siehe core/docker_sandbox.py) - keine Host-venv.
            rel = req_file.relative_to(self.project_dir).as_posix()
            install_result = DockerSandbox.run_python(["pip", "install", "-q", "-r", rel], self.project_dir, timeout_seconds)
            return sanitize_note + self._pip_status_line(req_file, install_result, " [Docker-Sandbox]")

        venv_python = self._venv_python()
        if not venv_python.exists():
            create_result = CodeSandbox.run_command(
                [sys.executable, "-m", "venv", str(self.project_dir / VENV_DIRNAME)],
                cwd=self.project_dir,
                timeout_seconds=60.0,
            )
            if create_result.exit_code != 0:
                return sanitize_note + f"⚠️ Konnte keine isolierte venv anlegen (nutze System-Interpreter als Fallback): {create_result.stderr[:300]}"

        target_python = venv_python if venv_python.exists() else Path(sys.executable)
        install_result = CodeSandbox.run_command(
            [str(target_python), "-m", "pip", "install", "-q", "-r", str(req_file)],
            cwd=self.project_dir,
            timeout_seconds=timeout_seconds,
        )
        return sanitize_note + self._pip_status_line(req_file, install_result)

    def _ensure_pytest_available(self, timeout_seconds: float) -> str:
        """
        Team-Optimierung (echter Fund: memory/backlog.json-Tickets `recurring-failure-
        event_relay` und `recurring-failure-service_bookmark_monitor`). core/verifier/
        testrunner.py._run_pytest_or_unittest() prüft vor jedem Testlauf `import pytest` und
        fällt bei Fehlschlag STILLSCHWEIGEND auf `python -m unittest discover` zurück - das
        findet dabei aber fast IMMER 0 Tests ("Ran 0 tests in 0.000s / NO TESTS RAN"), weil
        generierter Testcode praktisch ausschließlich im pytest-Stil geschrieben wird (einfache
        `def test_...()`-Funktionen ohne `unittest.TestCase`-Basisklasse), die unittests eigene
        Discovery gar nicht als Tests erkennt. Der anschließende Fix-Loop
        (agents/orchestrator/verification.py) konnte diesem "Testfehler" mangels Traceback/
        Datei-Bezug keinen Agenten sinnvoll zuordnen und beauftragte blind den `tester` (siehe
        dortiger Fallback `if not owners: owners = {"tester"}`) - der konnte das Problem nie
        lösen ("Fixversuch änderte nichts"), weil die eigentliche Ursache (fehlendes `pytest` in
        requirements.txt/requirements-dev.txt) außerhalb seiner Zuständigkeit liegt: er kann
        Testdateien schreiben, aber nicht wissen, dass die Umgebung sie gar nicht ausführen kann.

        `pytest` ist das vom FRAMEWORK selbst gewählte Test-Werkzeug (core/verifier/testrunner.py
        entscheidet sich dafür, nicht der generierte Code) - stellt seine Verfügbarkeit deshalb
        unabhängig davon sicher, ob der jeweilige Agent daran gedacht hat, es als Abhängigkeit
        aufzunehmen, statt das strukturell nie lösbare Symptom im Fix-Loop zu bekämpfen. Ein
        Installationsfehlschlag (z.B. kein Netzwerkzugriff) lässt run_tests() bewusst unverändert
        auf den bereits bestehenden `import pytest`-Check/unittest-Fallback zurückfallen, statt
        den gesamten Lauf zu blockieren.
        """
        # Team-Optimierung (Bericht `ki_team_schwachstellen_und_fehleranalyse_aethermesh_
        # 20260913.md`, Schwachstelle 1): `pytest-asyncio` wird neben `pytest` ebenfalls
        # sichergestellt, weil generierter Code bei FastAPI/asyncio-Projekten praktisch
        # immer `async def test_...`-Funktionen enthält. Ohne das Plugin werden solche Tests
        # von pytest stillschweigend übersprungen ("async def functions are not natively
        # supported"), was reflexartig zu `verification_ok: false` führt, obwohl der Code
        # fehlerfrei ist. Die Aktivierung selbst (`asyncio_mode=auto`) erfolgt zusätzlich als
        # CLI-Flag in core/verifier/testrunner.py, damit sie auch ohne agentengenerierte
        # pytest.ini greift.
        if DockerSandbox.is_active():
            sandbox_result = DockerSandbox.run_python(
                [
                    "sh", "-c",
                    "python -c 'import pytest, pytest_asyncio' 2>/dev/null && exit 0; "
                    "pip install -q pytest pytest-asyncio && echo AI_TEAM_PYTEST_INSTALLED",
                ],
                self.project_dir, timeout_seconds,
            )
            if sandbox_result.exit_code == 0 and "AI_TEAM_PYTEST_INSTALLED" not in sandbox_result.stdout:
                return ""
            status = "✅" if sandbox_result.exit_code == 0 else "⚠️"
            return (
                f"{status} `pytest`/`pytest-asyncio` fehlten in der Umgebung (nicht in requirements.txt/"
                f"requirements-dev.txt) - im Docker-Sandbox-Volume nachinstalliert (exit_code={sandbox_result.exit_code})"
            )

        target_python = self._venv_python() if self._venv_python().exists() else Path(sys.executable)
        check = CodeSandbox.run_command(
            [str(target_python), "-c", "import pytest, pytest_asyncio"], cwd=self.project_dir, timeout_seconds=10.0,
        )
        if check.exit_code == 0:
            return ""
        install_result = CodeSandbox.run_command(
            [str(target_python), "-m", "pip", "install", "-q", "pytest", "pytest-asyncio"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )
        status = "✅" if install_result.exit_code == 0 else "⚠️"
        return (
            f"{status} `pytest`/`pytest-asyncio` fehlten in der Umgebung (nicht in requirements.txt/"
            f"requirements-dev.txt) - nachinstalliert (exit_code={install_result.exit_code})"
        )

    # Team-Optimierung (`/goal`-Auftrag, Schwachstelle 2 aus den Laeufen eventstream_zero/
    # aethermesh/chronospulse/incident_pulse): `agents/team_directives.py._PYTEST_ASYNCIO_
    # CONFIG_RULE` weist Architect/Tester zwar an, selbst eine `pytest.ini` mit
    # `asyncio_mode = auto` anzulegen - verlaesst sich dafuer aber allein auf das LLM. Bleibt
    # dieser Schritt aus (vergessen, abgebrochener Lauf, Modell haelt sich nicht daran), griff
    # bisher nur noch der CLI-Fallback `-o asyncio_mode=auto` in testrunner.py - der deckt zwar
    # die vom Framework selbst gestartete Sandbox-Testausfuehrung ab, nicht aber einen manuellen
    # `pytest`-Aufruf im ausgelieferten Projekt (z.B. durch den Kunden oder CI/CD ausserhalb
    # dieser Sandbox), wo ohne `asyncio_mode = auto` jede `async def test_...`-Funktion
    # stillschweigend uebersprungen wird ("async def functions are not natively supported").
    # Deterministisches Scaffolding VOR dem ersten Testlauf schliesst diese Luecke unabhaengig
    # vom LLM-Verhalten: existiert bereits eine `pytest.ini` (typischerweise vom Architect/
    # Tester selbst angelegt), wird sie NIEMALS ueberschrieben - eine dort bereits vorhandene
    # projektspezifische Konfiguration (z.B. `testpaths`, `markers`) darf nicht verloren gehen.
    def _ensure_pytest_ini(self) -> str:
        pytest_ini = self.project_dir / "pytest.ini"
        if pytest_ini.exists():
            return self._repair_malformed_pytest_ini(pytest_ini)
        if not any(
            "async def test_" in src or "pytest.mark.asyncio" in src
            for src in self._read_python_test_sources()
        ):
            return ""
        try:
            pytest_ini.write_text(
                "[pytest]\nasyncio_mode = auto\npythonpath = .\n", encoding="utf-8",
            )
        except OSError as e:
            return f"⚠️ Konnte pytest.ini nicht deterministisch anlegen: {e}"
        return "✅ pytest.ini (asyncio_mode=auto, pythonpath=.) deterministisch angelegt - Projekt enthaelt async-Tests, aber keine eigene pytest.ini."

    # Realer Fund (cloudpulse, 2026-09-16, Schwachstelle 3): ein Agent schrieb eine `pytest.ini`,
    # deren Zeilen eingerueckt waren. pytest bricht darauf mit Exit-Code 4 ab
    # ("pytest.ini:1: unexpected value continuation") - KEIN einziger Test wird gesammelt, und
    # der Fehler sieht in den Logs wie ein Testfehler aus. Das kostete einen vollstaendigen
    # Tester-Agentenaufruf (61 s, 103k Tokens) fuer eine reine Whitespace-Korrektur. Eine
    # eingerueckte Sektionsueberschrift bzw. eine eingerueckte Zeile VOR der ersten Sektion hat
    # in einer INI-Datei nie eine gueltige Bedeutung; sie laesst sich deshalb gefahrlos
    # deterministisch geradeziehen. Echte Mehrzeilen-Werte (z.B. ein eingeruecktes `addopts`-
    # Fortsetzungsfragment NACH einem Schluessel) bleiben dabei unangetastet.
    _INI_OPTION_RE = re.compile(r"^[A-Za-z_][\w.\-]*\s*=")

    def _repair_malformed_pytest_ini(self, pytest_ini: Path) -> str:
        try:
            original = pytest_ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        repaired: list[str] = []
        changed = False
        # Eine eingerueckte Zeile ist nur dann eine gueltige Wert-Fortsetzung, wenn davor
        # ueberhaupt ein Schluessel steht (`addopts =` plus eingerueckte Folgezeilen). Direkt
        # nach einer Sektionsueberschrift oder am Dateianfang gibt es keinen Wert, der
        # fortgesetzt werden koennte - dort ist die Einrueckung immer ein Formatierungsfehler
        # des Modells und wird entfernt.
        continuation_allowed = False
        for line in original.splitlines():
            stripped = line.strip()
            if not stripped:
                repaired.append(line)
                continue
            is_indented = line[:1] in (" ", "\t")
            is_section = stripped.startswith("[") and stripped.endswith("]")
            is_comment = stripped.startswith(("#", ";"))
            # Eine eingerueckte Zeile, die selbst wie `schluessel = wert` aussieht, ist nie
            # eine Wert-Fortsetzung, sondern eine verrutschte Option (`    asyncio_mode = auto`).
            # Echte Fortsetzungen sind Werte-Fragmente (`-q`, `--strict-markers`,
            # `slow: langsame Tests`) und bleiben deshalb unangetastet.
            looks_like_option = bool(self._INI_OPTION_RE.match(stripped))
            if is_indented and not is_comment and (looks_like_option or not continuation_allowed):
                repaired.append(stripped)
                changed = True
            else:
                repaired.append(line)
            if is_section:
                continuation_allowed = False
            elif not is_comment and ("=" in stripped or ":" in stripped):
                continuation_allowed = True
        if not changed:
            return ""
        try:
            pytest_ini.write_text('\n'.join(repaired) + '\n', encoding="utf-8")
        except OSError as e:
            return f"⚠️ Konnte fehlerhafte pytest.ini nicht reparieren: {e}"
        return (
            "✅ pytest.ini deterministisch repariert - eingerueckte Zeilen haetten pytest mit "
            "'unexpected value continuation' (Exit-Code 4) abbrechen lassen, bevor ein Test laeuft."
        )

    # Team-Optimierung (NexusForge-Lauf, Schwachstelle 3): _ensure_pytest_available()/
    # _ensure_pytest_ini() oben sichern nur die LAUFZEIT-Umgebung der eigenen Sandbox ab, wenn
    # async-Tests existieren - requirements.txt selbst bleibt dabei unverändert. Der
    # nachgelagerte core/verifier/completeness.py._missing_async_test_dependencies()-Check prüft
    # aber ausschließlich das MANIFEST (statisch, unabhängig von der Sandbox-Installation), findet
    # dort weder `pytest-asyncio` noch `anyio` und meldet `verification_ok: false`, obwohl die
    # Tests in der Sandbox längst grün liefen. Analog zum bestehenden Sanitizer für toxische
    # Abhängigkeiten (core/manifest_guard.sanitize_requirements_file()) wird `pytest-asyncio`
    # deshalb deterministisch an requirements.txt angehängt, statt auf den Agenten zu hoffen - nur
    # wenn requirements.txt bereits existiert (sonst gäbe es kein Manifest, das completeness.py
    # überhaupt prüft - das fehlende Manifest selbst meldet bereits _missing_dependency_manifest())
    # und weder `pytest-asyncio` noch `anyio` schon gelistet sind.
    def _ensure_async_test_manifest_entry(self) -> str:
        # Test-Plugin -> requirements-dev.txt (nicht in die Produktions-Abhängigkeiten); beide
        # Manifeste zählen bei der Prüfung, ob es bereits gelistet ist.
        requirements_txt = self.project_dir / "requirements.txt"
        dev_requirements = self.project_dir / "requirements-dev.txt"
        if not requirements_txt.exists():
            return ""
        if not any(
            "async def test_" in src or "pytest.mark.asyncio" in src
            for src in self._read_python_test_sources()
        ):
            return ""
        try:
            content = requirements_txt.read_text(encoding="utf-8", errors="ignore")
            dev_content = dev_requirements.read_text(encoding="utf-8", errors="ignore") if dev_requirements.exists() else ""
        except OSError as e:
            return f"⚠️ Konnte requirements.txt nicht auf pytest-asyncio/anyio prüfen: {e}"
        if _ASYNC_TEST_DEPENDENCY_TOKEN_RE.search((content + "\n" + dev_content).lower().replace("_", "-")):
            return ""
        separator = "" if (not dev_content or dev_content.endswith("\n")) else "\n"
        try:
            dev_requirements.write_text(dev_content + separator + "pytest-asyncio\n", encoding="utf-8")
        except OSError as e:
            return f"⚠️ Konnte `pytest-asyncio` nicht deterministisch in requirements-dev.txt eintragen: {e}"
        return (
            "✅ `pytest-asyncio` deterministisch an requirements-dev.txt angehängt - Projekt enthält "
            "async-Tests, aber weder `pytest-asyncio` noch `anyio` waren im Dependency-Manifest "
            "gelistet."
        )

    def _read_python_test_sources(self) -> list[str]:
        sources: list[str] = []
        for test_file in self._find_python_test_files():
            try:
                sources.append(test_file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return sources

    def _ensure_node_environment(self, node_dir: Path, timeout_seconds: float) -> str:
        """
        Team-Goal (20260913, Aufgabe 2): unter Windows scheiterte `npm test` gelegentlich daran,
        dass lokale `node_modules` noch nicht installiert waren, ODER `jest` als globaler Befehl
        im CMD-Pfad fehlte ("Der Befehl 'jest' ist entweder falsch geschrieben..."), obwohl
        `package.json` bereits ein reines `"test": "jest"`-Skript deklarierte. Deterministisches
        Scaffolding statt Hoffnung auf eine bereits vorhandene globale Jest-Installation:
        - `node_modules` fehlt -> `npm ci` (bei vorhandener package-lock.json, deterministisch)
          bzw. `npm install --prefer-offline --no-audit` (schneller, kein unnötiger Netzwerk-/
          Audit-Overhead in der Sandbox). Existiert `node_modules` bereits (z.B. ein vorheriger
          Verifikations-Durchlauf im selben Projektordner), wird die Installation übersprungen -
          spart Zeit UND vermeidet ein unnötiges erneutes `npm ci`, das package-lock.json strikt
          gegen package.json validiert und bei jeder Abweichung fehlschlägt.
        - Ein `"test"`-Skript, das WÖRTLICH nur `"jest"` lautet, wird auf `"npx jest"`
          umgeschrieben - `npx` löst die lokal installierte `node_modules/.bin/jest`-Binary
          zuverlässig auf, unabhängig davon, ob `jest` global im PATH registriert ist.
        """
        rel = self._relative_label(node_dir)
        sandbox_active = DockerSandbox.is_active()
        if not sandbox_active and shutil.which("npm") is None:
            return f"⚠️ `npm` ist auf diesem System nicht installiert/verfügbar – Node-Abhängigkeiten ({rel}) übersprungen."

        logs: list[str] = []
        if (node_dir / "node_modules").is_dir():
            logs.append(f"✅ node_modules bereits vorhanden ({rel}) - Installation übersprungen.")
        else:
            command = (
                ["npm", "ci"] if (node_dir / "package-lock.json").exists()
                else ["npm", "install", "--prefer-offline", "--no-audit"]
            )
            if sandbox_active:
                # postinstall-Skripte laufen im Container; node_modules liegt in einem Volume.
                install_result = DockerSandbox.run_node(command, self.project_dir, node_dir, timeout_seconds)
            else:
                install_result = CodeSandbox.run_command(command, cwd=node_dir, timeout_seconds=timeout_seconds)
            status = "✅" if install_result.exit_code == 0 else "⚠️"
            tail = (install_result.stdout + install_result.stderr).strip()[-800:]
            label = f"{' '.join(command)} ({rel})" + (" [Docker-Sandbox]" if sandbox_active else "")
            logs.append(f"{status} {label} (exit_code={install_result.exit_code})" + (f"\n{tail}" if install_result.exit_code != 0 else ""))

        jest_log = self._ensure_robust_jest_test_script(node_dir, rel)
        if jest_log:
            logs.append(jest_log)
        return "\n".join(logs)

    def _ensure_robust_jest_test_script(self, node_dir: Path, rel: str) -> str:
        """Schreibt ein `package.json`-`"test"`-Skript, das WÖRTLICH nur `"jest"` lautet, auf
        `"npx jest"` um - siehe _ensure_node_environment()-Docstring. Bewusst konservativ: nur
        der exakte String `"jest"` (nach Trimmen) wird ersetzt, ein bereits differenzierteres
        Skript (`"jest --coverage"`, `"jest --ci"`, `"react-scripts test"`, ...) bleibt
        unangetastet, um keine bewusste Agenten-Konfiguration zu überschreiben."""
        pkg_json = node_dir / "package.json"
        try:
            raw = pkg_json.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return ""
        scripts = data.get("scripts")
        if not isinstance(scripts, dict) or scripts.get("test", "").strip() != "jest":
            return ""
        scripts["test"] = "npx jest"
        try:
            pkg_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as e:
            return f"⚠️ Konnte '\"test\": \"jest\"' in package.json ({rel}) nicht auf 'npx jest' umstellen: {e}"
        return f"✅ package.json ({rel}): Test-Skript 'jest' -> 'npx jest' umgestellt (robust gegen fehlende globale Jest-Binary unter Windows)."

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

    def _find_node_build_projects(self) -> list[Path]:
        """
        Findet alle package.json-Verzeichnisse im Projekt (node_modules & Co. ausgeschlossen),
        die ein "build"-Skript deklarieren – dieselbe Suche wie _find_node_projects() oben, nur
        mit "build" statt "test" als Filterkriterium (siehe RuntimeMixin.check_frontend_build()
        für den vollen Kontext: ein "test"-Skript und ein "build"-Skript prüfen unterschiedliche
        Dinge und ein Projekt kann beide, nur eines oder keines von beiden deklarieren).
        """
        projects: list[Path] = []
        for pkg_json in self.project_dir.rglob("package.json"):
            if any(part in _IGNORED_DIRS for part in pkg_json.relative_to(self.project_dir).parts):
                continue
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data.get("scripts"), dict) and data["scripts"].get("build"):
                projects.append(pkg_json.parent)
        return projects

    def _resolve_python(self) -> str:
        venv_python = self._venv_python()
        return str(venv_python) if venv_python.exists() else sys.executable

    def _has_python_files(self) -> bool:
        return any(
            f for f in self.project_dir.rglob("*.py")
            if not any(part in _IGNORED_DIRS for part in f.parts)
        )
