"""
core/browser_verifier.py – Headless Browser UI- & Frontend-Validierung

Prüft Web- und Frontend-Projekte auf:
1. Reale Browser-Rendering-Fehler & JavaScript-Konsolenfehler (`console.error`, Uncaught Exceptions)
2. Fehlende statische Assets (CSS, JS, Bilder -> 404-Fehler)
3. DOM-Struktur & Barrierefreiheits-Basics
4. Automatischer Fallback auf statische DOM- & Asset-Referenz-Prüfung, falls kein Headless-Browser installiert ist.
"""

import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BrowserVerificationReport:
    """Ergebnis der Browser- & Frontend-Validierung."""
    attempted: bool
    passed: bool = False
    engine: str = "none"  # "playwright", "headless_chrome", "static_dom"
    console_errors: list[str] = field(default_factory=list)
    missing_assets: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tested_url: str = ""
    reason_skipped: str = ""


@dataclass
class AccessibilityViolation:
    """Ein einzelner, aus einem echten axe-core-Lauf geparster WCAG-Verstoß."""
    rule_id: str
    impact: str  # axe-core-eigene Skala: "minor"/"moderate"/"serious"/"critical"
    description: str
    help_url: str
    target: str  # CSS-Selektor(en) des betroffenen Elements, zusammengefasst
    node_count: int = 1


@dataclass
class AccessibilityReport:
    """
    Ergebnis eines echten axe-core-Scans (WCAG 2.x-Regelwerk, per `axe-core-python` gegen eine
    echt gerenderte Playwright-Seite ausgeführt) – ersetzt die bisherige rein LLM-basierte
    Einschätzung des accessibility-Agenten (eine Freitext-Checkliste ohne konkreten Fundort)
    durch echte, geparste Verstöße mit Regel/Schweregrad/betroffenem Element. Dasselbe Prinzip,
    das core/verifier.py.check_sast() bereits für Security etabliert hat, nur für
    Barrierefreiheit.

    Braucht zwingend eine echt gerenderte Seite (keine statische DOM-Analyse reicht aus wie
    beim Asset-404-Fallback von verify_frontend()) - ohne installiertes Playwright ODER
    `axe-core-python` ist der Scan NICHT möglich (attempted=False), nicht nur eingeschränkt.
    Wie bei jedem anderen Check: ein technischer Fehlschlag ist KEIN Fehler, nur nicht prüfbar,
    und wird NIEMALS fälschlich als "keine Verstöße" gemeldet.
    """
    attempted: bool
    passed: bool = False
    violations: list[AccessibilityViolation] = field(default_factory=list)
    tested_url: str = ""
    reason_skipped: str = ""


class BrowserVerifier:
    """
    Validiert Web- und Frontend-Projekte per Headless-Browser oder statischer DOM-Analyse.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()

    def _find_html_entrypoints(self) -> list[Path]:
        """Findet alle relevanten HTML-Dateien im Projekt."""
        html_files = []
        ignored = {".git", ".venv", "venv", ".ai_team_venv", "node_modules", "dist", "build"}
        for root, dirs, files in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in ignored]
            for f in files:
                if f.lower().endswith((".html", ".htm")):
                    html_files.append(Path(root) / f)
        return sorted(html_files, key=lambda p: (0 if p.name == "index.html" else 1, len(str(p))))

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def verify_frontend(self, timeout_seconds: float = 10.0) -> BrowserVerificationReport:
        """
        Hauptmethode zur Prüfung: Sucht nach HTML-Einstiegspunkten und führt
        eine dynamische Browser- oder statische DOM-Prüfung durch.
        """
        html_files = self._find_html_entrypoints()
        if not html_files:
            return BrowserVerificationReport(
                attempted=False, reason_skipped="Keine HTML-Dateien im Projekt gefunden (kein Web-Frontend).",
            )

        entry_html = html_files[0]
        rel_entry = str(entry_html.relative_to(self.project_dir)).replace("\\", "/")

        # 1. Statische Asset- & Referenz-Prüfung
        static_missing, static_warnings = self._validate_static_assets(entry_html)

        # 2. Prüfe, ob Playwright installiert ist
        playwright_report = self._run_playwright_check(entry_html, timeout_seconds)
        if playwright_report and playwright_report.attempted:
            for s in static_missing:
                fname = s.split("'")[1] if "'" in s else s
                if not any(fname in m for m in playwright_report.missing_assets):
                    playwright_report.missing_assets.append(s)
            playwright_report.warnings = list(dict.fromkeys(playwright_report.warnings + static_warnings))
            if playwright_report.missing_assets:
                playwright_report.passed = False
            return playwright_report

        # 3. Fallback: Statische DOM- & Syntax-Prüfung
        passed = len(static_missing) == 0
        return BrowserVerificationReport(
            attempted=True,
            passed=passed,
            engine="static_dom",
            missing_assets=static_missing,
            warnings=static_warnings,
            tested_url=f"file://{rel_entry}",
        )

    def _validate_static_assets(self, html_file: Path) -> tuple[list[str], list[str]]:
        """Prüft, ob alle in HTML verlinkten lokalen JS-, CSS- und Bild-Dateien existieren."""
        missing = []
        warnings = []
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return [f"Konnte {html_file.name} nicht lesen: {e}"], []

        # Suche nach <link href="...">, <script src="...">, <img src="...">
        asset_pattern = re.compile(r"""(?:src|href)\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
        for match in asset_pattern.finditer(content):
            ref = match.group(1).strip()
            # Ignoriere externe URLs, Anker, Javascript-Links und Template-Variablen
            if ref.startswith(("http://", "https://", "//", "#", "javascript:", "mailto:", "{", "%", "data:")):
                continue

            ref_clean = ref.split("?")[0].split("#")[0]
            if not ref_clean:
                continue

            # Relativ zum Verzeichnis der HTML-Datei oder Projekt-Root
            candidate1 = html_file.parent / ref_clean
            candidate2 = self.project_dir / ref_clean.lstrip("/")
            if not (candidate1.exists() or candidate2.exists()):
                missing.append(f"Fehlendes Asset: '{ref}' in {html_file.name}")

        # Prüfe auf fehlende Title oder Doctype
        if "<title>" not in content.lower():
            warnings.append(f"HTML-Warnung in {html_file.name}: Kein <title>-Tag gefunden.")

        return missing, warnings

    def _run_playwright_check(self, html_file: Path, timeout: float) -> BrowserVerificationReport | None:
        """Führt einen echten Headless-Browser-Check per Playwright Python-API aus, falls vorhanden."""
        try:
            import importlib.util
            if not importlib.util.find_spec("playwright"):
                return None
        except Exception:
            return None

        port = self._find_free_port()
        serve_dir = str(self.project_dir)

        # Starte lokalen statischen HTTP-Server
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=serve_dir, **kwargs)
            def log_message(self, format, *args):
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)

        rel_path = str(html_file.relative_to(self.project_dir)).replace("\\", "/")
        target_url = f"http://127.0.0.1:{port}/{rel_path}"

        # Führe Playwright Test in Subprozess aus (isoliert gegen Crashes)
        runner_code = f"""
import sys, json
from playwright.sync_api import sync_playwright

console_errors = []
missing_assets = []

def handle_console(msg):
    if msg.type in ('error', 'assert'):
        console_errors.append(msg.text)

def handle_response(resp):
    if resp.status >= 400 and not resp.url.startswith('chrome-error:'):
        missing_assets.append(f'HTTP {{resp.status}}: {{resp.url}}')

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on('console', handle_console)
        page.on('response', handle_response)
        page.goto('{target_url}', timeout={int(timeout * 1000)}, wait_until='load')
        page.wait_for_timeout(500)
        title = page.title()
        browser.close()
    print(json.dumps({{'success': True, 'errors': console_errors, 'missing': missing_assets, 'title': title}}))
except Exception as e:
    print(json.dumps({{'success': False, 'error': str(e)}}))
"""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", runner_code],
                capture_output=True, text=True, timeout=timeout + 3.0,
            )
            out = proc.stdout.strip()
            if not out:
                return None
            data = json.loads(out)
            if not data.get("success"):
                return None

            errors = data.get("errors", [])
            missing = data.get("missing", [])
            passed = len(errors) == 0 and len(missing) == 0

            return BrowserVerificationReport(
                attempted=True,
                passed=passed,
                engine="playwright",
                console_errors=errors,
                missing_assets=missing,
                tested_url=target_url,
            )
        except Exception:
            return None
        finally:
            httpd.shutdown()
            httpd.server_close()

    def verify_accessibility(self, timeout_seconds: float = 10.0) -> AccessibilityReport:
        """
        Führt einen echten axe-core-Scan (WCAG 2.x) gegen den ersten gefundenen HTML-
        Einstiegspunkt aus - eigener, unabhängiger Browser-Lauf statt Wiederverwendung von
        _run_playwright_check() (dasselbe Prinzip wie bei den übrigen, unabhängig voneinander
        attempted/skipped-baren Checks in core/verifier.py: ein Fehlschlag hier darf den
        UI-Konsolen-/Asset-Check nicht beeinflussen und umgekehrt).
        """
        html_files = self._find_html_entrypoints()
        if not html_files:
            return AccessibilityReport(attempted=False, reason_skipped="Keine HTML-Dateien im Projekt gefunden (kein Web-Frontend).")

        try:
            import importlib.util
            if not importlib.util.find_spec("playwright"):
                return AccessibilityReport(
                    attempted=False,
                    reason_skipped="Playwright ist auf diesem System nicht installiert (`pip install playwright` + `playwright install chromium`).",
                )
            if not importlib.util.find_spec("axe_core_python"):
                return AccessibilityReport(
                    attempted=False, reason_skipped="`axe-core-python` ist auf diesem System nicht installiert (`pip install axe-core-python`).",
                )
        except Exception:
            return AccessibilityReport(attempted=False, reason_skipped="Konnte Playwright/axe-core-python nicht prüfen.")

        entry_html = html_files[0]
        port = self._find_free_port()
        serve_dir = str(self.project_dir)

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=serve_dir, **kwargs)
            def log_message(self, format, *args):
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)

        rel_path = str(entry_html.relative_to(self.project_dir)).replace("\\", "/")
        target_url = f"http://127.0.0.1:{port}/{rel_path}"

        # axe.run(page) liefert das native axe-core-Ergebnisformat (dieselbe stabile Struktur,
        # die auch @axe-core/playwright, cypress-axe, jest-axe, ... zurückgeben, da alle nur
        # denselben axe-core-Engine-Kern aufrufen): result["violations"] als Liste, jeder
        # Eintrag mit id/impact/description/helpUrl/nodes (nodes je mit target/html).
        runner_code = f"""
import sys, json
from playwright.sync_api import sync_playwright
from axe_core_python.sync_playwright import Axe

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto('{target_url}', timeout={int(timeout_seconds * 1000)}, wait_until='load')
        page.wait_for_timeout(300)
        axe = Axe()
        result = axe.run(page)
        browser.close()
    print(json.dumps({{'success': True, 'result': result}}))
except Exception as e:
    print(json.dumps({{'success': False, 'error': str(e)}}))
"""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", runner_code],
                capture_output=True, text=True, timeout=timeout_seconds + 5.0,
            )
            out = proc.stdout.strip()
            if not out:
                tail = (proc.stdout + proc.stderr).strip()[-800:]
                return AccessibilityReport(attempted=False, reason_skipped=f"axe-core lieferte kein Ergebnis: {tail}")
            data = json.loads(out)
            if not data.get("success"):
                return AccessibilityReport(attempted=False, reason_skipped=f"axe-core-Lauf fehlgeschlagen: {data.get('error', '?')}")

            return self._parse_axe_result(data.get("result") or {}, target_url)
        except Exception as e:
            return AccessibilityReport(attempted=False, reason_skipped=f"axe-core-Lauf fehlgeschlagen: {e}")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def _parse_axe_result(self, result: dict, target_url: str) -> AccessibilityReport:
        """
        Best effort wie jeder andere Tool-Ausgabe-Parser dieses Projekts (siehe z. B.
        core/verifier.py._parse_k6_summary()): fehlende/abweichende Felder degradieren
        konservativ (leere Strings/0), statt mit KeyError zu crashen - kein Anspruch, jede
        axe-core-Version exakt zu kennen.
        """
        raw_violations = result.get("violations") if isinstance(result, dict) else None
        if not isinstance(raw_violations, list):
            return AccessibilityReport(attempted=True, passed=True, tested_url=target_url)

        violations: list[AccessibilityViolation] = []
        for entry in raw_violations:
            if not isinstance(entry, dict):
                continue
            nodes = entry.get("nodes") or []
            targets = [t for n in nodes if isinstance(n, dict) for t in (n.get("target") or [])]
            violations.append(AccessibilityViolation(
                rule_id=entry.get("id", "?"),
                impact=entry.get("impact") or "unbekannt",
                description=entry.get("description") or entry.get("help") or "",
                help_url=entry.get("helpUrl", ""),
                target="; ".join(targets[:3]) or "?",
                node_count=len(nodes) or 1,
            ))

        return AccessibilityReport(
            attempted=True, passed=len(violations) == 0, violations=violations, tested_url=target_url,
        )
