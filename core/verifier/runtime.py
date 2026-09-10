"""
core/verifier/runtime.py – RuntimeMixin: echte Laufzeit-Verifikation statt Keyword-Raten.

check_docker_build() versucht einen echten `docker build`, falls ein Dockerfile existiert.

check_runtime_smoke() prüft durch einen kurzen Teststart im Subprozess, ob die generierte
App tatsächlich lauffähig ist (Web-/API-Apps, CLI-Skripte, Node.js-Server).

check_browser_ui()/check_accessibility() delegieren an core/browser_verifier.py.

check_load_test() führt die vom performance-Agenten geschriebenen k6-/Locust-Lastentest-
Skripte tatsächlich AUS (bisher landeten sie ungeprüft im Projekt, niemand wusste, ob sie
überhaupt liefen) – startet die generierte App auf einem freien Port und lässt einen kurzen,
wenige Sekunden dauernden Smoke-Lasttest dagegen laufen, kein vollständiger Lasttest.
"""

import csv
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.code_sandbox import CodeSandbox
from core.docker_sandbox import DockerSandbox
from core.verifier.models import (
    _DOCKER_DAEMON_UNAVAILABLE_RE,
    LOAD_TEST_DIRNAME,
    DockerBuildReport,
    FrontendBuildReport,
    PerfCheckReport,
    RuntimeSmokeReport,
    _csv_float,
)


class RuntimeMixin:
    """Führt echte Laufzeit-/Deployment-/Lastentest-Checks für ein Projekt aus."""

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
        if result.exit_code != 0 and _DOCKER_DAEMON_UNAVAILABLE_RE.search(output):
            return DockerBuildReport(
                attempted=False, success=True, output=output,
                reason_skipped="Docker-Daemon lokal nicht erreichbar (z.B. Docker Desktop nicht "
                               "gestartet) - keine Aussage über die Codequalität, nur nicht prüfbar.",
            )
        return DockerBuildReport(attempted=True, success=result.exit_code == 0, output=output)

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

    def check_frontend_build(self, timeout_seconds: float = 180.0) -> list[FrontendBuildReport]:
        """
        Führt einen echten `npm run build` für jedes gefundene Frontend-Projekt aus (package.json
        mit "build"-Skript unter `frontend/` oder im Projekt-Root, siehe
        EnvironmentMixin._find_node_build_projects()). TypeScript-Typfehler, ungelöste Imports
        oder ungültiges JSX/CSS brechen dabei denselben Bundler/Compiler (Vite/webpack/tsc), den
        auch ein echtes Deployment nutzen würde - anders als `npm test` (das oft gar nicht
        existiert oder etwas völlig anderes prüft als der Produktions-Build).
        """
        return [self._build_frontend(node_dir, timeout_seconds) for node_dir in self._find_node_build_projects()]

    def _build_frontend(self, node_dir: Path, timeout_seconds: float) -> FrontendBuildReport:
        rel = self._relative_label(node_dir)
        if DockerSandbox.is_active():
            # node_modules liegt im Sandbox-Volume (core/docker_sandbox.py), nicht auf dem Host -
            # der Build muss deshalb ebenfalls im Container laufen. Exit 90 = keine Installation.
            result = DockerSandbox.run_node(
                ["sh", "-c", 'if [ -z "$(ls -A node_modules 2>/dev/null)" ]; then exit 90; fi; exec npm run build'],
                self.project_dir, node_dir, timeout_seconds,
            )
            if result.exit_code == 0:
                return FrontendBuildReport(attempted=True, passed=True, directory=rel)
            if result.exit_code == 90:
                return FrontendBuildReport(
                    attempted=True, passed=False, directory=rel,
                    output=f"`npm install`/`npm ci` hat unter {rel} im Docker-Sandbox-Volume keine node_modules "
                           "erzeugt (Installation fehlgeschlagen oder abgebrochen) - der Frontend-Build kann so "
                           "nicht ausgeführt werden.",
                )
            return FrontendBuildReport(
                attempted=True, passed=False, directory=rel, output=(result.stdout + result.stderr).strip()[-4000:],
            )
        if shutil.which("npm") is None:
            return FrontendBuildReport(
                attempted=False, passed=True, directory=rel,
                reason_skipped="`npm` ist auf diesem System nicht installiert/verfügbar.",
            )
        if not (node_dir / "node_modules").exists():
            # Team-Optimierung (echter Fund): `npm` ist auf dem System vorhanden -
            # EnvironmentMixin.ensure_environment() führt für JEDES Frontend-Projekt mit
            # "build"-Skript bereits `npm install`/`npm ci` aus, BEVOR dieser Check überhaupt
            # läuft. Fehlende node_modules bedeuten an dieser Stelle deshalb nicht "wurde nicht
            # ausgeführt", sondern fast immer "die Installation ist fehlgeschlagen" (Netzwerk,
            # ungültige package.json, fehlende Registry-Auth, ...). Das bisherige stille
            # passed=True überspringen ließ ein kaputtes/unvollständiges Frontend als "geprüft und
            # bestanden" durchgehen - jetzt gilt eine fehlende node_modules-Installation trotz
            # verfügbarem npm als fehlgeschlagener Build, der ans Team zurückgemeldet wird.
            return FrontendBuildReport(
                attempted=True, passed=False, directory=rel,
                output=f"`npm install`/`npm ci` hat unter {rel} offenbar keine node_modules "
                       "erzeugt (Installation fehlgeschlagen oder abgebrochen) - der Frontend-"
                       "Build kann so nicht ausgeführt werden.",
            )
        result = CodeSandbox.run_command(["npm", "run", "build"], cwd=node_dir, timeout_seconds=timeout_seconds)
        if result.exit_code == 0:
            return FrontendBuildReport(attempted=True, passed=True, directory=rel)
        output = (result.stdout + result.stderr).strip()[-4000:]
        return FrontendBuildReport(attempted=True, passed=False, directory=rel, output=output)

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
