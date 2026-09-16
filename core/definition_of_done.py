"""
core/definition_of_done.py – Maschinenlesbare, unbestechliche "Definition of Done" je Projekt

Realer Fund (KI-Team-Masterplan-Analyse, 09.09.2026): `PROJECT_STATE.md` von
workspace/event_ticket_api meldete "⚠️ In Entwicklung / Verifikation ausstehend" – bei
`files_written_count: 0`, also nachdem kein einziger Agent eine Zeile produziert hatte. Der
Projektzustand war damit reine Prosa: Er konnte nicht zwischen "fast fertig", "gar nicht erst
angefangen" und "an der Infrastruktur gescheitert" unterscheiden.

Genauso wenig gab es eine belastbare Quelle dafür, OB ein Projekt fertig ist. evals/runner.py
las den Zustand deshalb per Substring-Match aus dem Berichtstext – und der geprüfte Marker steht
in jedem Bericht, auch in gescheiterten (50 von 50 Benchmark-Läufen "bestanden").

Dieses Modul schreibt `.ai_team_dod.json`: harte, einzeln nachvollziehbare Kriterien statt eines
Prosa-Status. Der Lauf gilt nur dann als fertig, wenn jedes VERPFLICHTENDE Kriterium erfüllt ist.

Wie core/project_status.py: rein additiv, ein I/O-Fehler darf nie einen sonst erfolgreichen Lauf
zum Scheitern bringen.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DOD_FILENAME = ".ai_team_dod.json"


@dataclass
class Criterion:
    """Ein einzelnes, hart prüfbares Fertigstellungs-Kriterium."""
    key: str
    label: str
    passed: bool
    required: bool = True
    detail: str = ""
    # False, wenn das Kriterium für dieses Projekt gar nicht anwendbar ist (z.B. ein
    # Frontend-Build ohne package.json). Nicht anwendbare Kriterien blockieren nie - sonst
    # könnte ein reines Python-CLI-Projekt niemals "fertig" werden.
    applicable: bool = True

    @property
    def blocking(self) -> bool:
        return self.required and self.applicable and not self.passed


@dataclass
class DefinitionOfDone:
    """Gesamtergebnis: Ist dieses Projekt fertig - und wenn nein, woran genau liegt es?"""
    project_slug: str
    timestamp: str = ""
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def blocking_criteria(self) -> list[Criterion]:
        return [c for c in self.criteria if c.blocking]

    @property
    def is_done(self) -> bool:
        """Fertig ist ein Projekt NUR, wenn kein verpflichtendes Kriterium offen ist."""
        return not self.blocking_criteria

    def to_dict(self) -> dict:
        return {
            "project_slug": self.project_slug,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(timespec="seconds"),
            "is_done": self.is_done,
            "blocking": [c.key for c in self.blocking_criteria],
            "criteria": [asdict(c) for c in self.criteria],
        }

    def format_summary(self) -> str:
        """Kurze, ehrliche Übersicht für Bericht und Konsole."""
        zeilen = ["### ✅ Definition of Done", ""]
        for c in self.criteria:
            if not c.applicable:
                symbol = "➖"
            elif c.passed:
                symbol = "✅"
            elif c.required:
                symbol = "❌"
            else:
                symbol = "⚠️"
            zusatz = f" – {c.detail}" if c.detail else ""
            zeilen.append(f"- {symbol} {c.label}{zusatz}")
        zeilen.append("")
        if self.is_done:
            zeilen.append("**Ergebnis: FERTIG** – alle verpflichtenden Kriterien erfüllt.")
        else:
            offen = ", ".join(c.label for c in self.blocking_criteria)
            zeilen.append(f"**Ergebnis: NICHT FERTIG** – offen: {offen}.")
        return "\n".join(zeilen)


_TEST_SCAN_IGNORED_DIRS = frozenset({".git", ".venv", "venv", ".ai_team_venv", "node_modules", "__pycache__", "dist", "build"})
_TEST_FILE_SUFFIXES = (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx")

# Realer Fund (pulseflow_gateway, 20260911_095217): verification_ok wurde true, obwohl im
# gesamten Workspace keine einzige Anwendungsdatei (main.py, Routen, Modelle) existierte - nur
# ADRs, README und drei Alibi-Smoke-Tests, die lediglich `__init__.py`/`requirements.txt` auf
# Existenz prüften. Ein Backend-/API-Projekt ohne echten Einstiegspunkt ist NIE fertig, egal wie
# grün die Testsuite aussieht.
_ENTRYPOINT_CANDIDATES = (
    "main.py", "app.py", "run.py", "server.py", "wsgi.py", "asgi.py",
    "app/main.py", "app/app.py", "src/main.py", "backend/main.py", "backend/app.py",
    "backend/app/main.py",
    # Team-Goal (20260913, Aufgabe 1): Web-/Hybrid-Einstiegspunkte (Lit/React/Vue/Cordova/...) -
    # ein reines Frontend- oder Hybrid-Mobile-Projekt hat nie eine Python-Serverdatei, ist aber
    # trotzdem fertig, wenn eines dieser Files existiert.
    "index.html", "ui-src/main.ts", "src/main.ts", "src/main.tsx", "src/index.ts",
    "src/index.js", "src/App.tsx", "src/App.jsx",
    # Realer Fund (dev_snippet_vault, 2026-09-15): der frontend-Agent lieferte ein vollständiges,
    # servierbares Frontend unter `public/index.html` (übliche Konvention für ein von einem
    # Python-Backend statisch ausgeliefertes Static-Asset) - diese Liste kannte nur root-level
    # `index.html` und meldete `missing_frontend_ui` trotz tatsächlich gelieferter UI.
    "public/index.html", "static/index.html",
)
_WEB_ENTRYPOINT_CANDIDATES = (
    "index.html", "ui-src/main.ts", "src/main.ts", "src/main.tsx", "src/index.ts",
    "src/index.js", "src/App.tsx", "src/App.jsx",
    "public/index.html", "static/index.html",
)
# Analyse 2026-09-15 (nexus_resilience_gateway): ein vollständiges, serverseitig ausgeliefertes
# Dashboard unter `app/static/dashboard.html` wurde nicht erkannt, weil nur feste Dateinamen galten.
# Jede nicht-leere HTML-Datei in einem typischen Auslieferungsordner zählt jetzt als geliefert.
_SERVED_UI_DIR_NAMES = frozenset({"static", "public", "templates", "www", "frontend", "web", "ui"})
_SERVED_UI_SKIP_DIRS = frozenset({"node_modules", ".venv", "venv", ".ai_team_venv", ".git", "dist", "build", "__pycache__"})
MIN_SERVED_HTML_BYTES = 200


def has_served_html_ui(project_dir: Path, max_depth: int = 3) -> bool:
    """True, wenn eine nicht-triviale HTML-Datei in static/, public/, templates/ ... liegt (bis Tiefe 3)."""
    root = Path(project_dir)
    if not root.is_dir():
        return False
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < max_depth and entry.name not in _SERVED_UI_SKIP_DIRS and not entry.name.startswith("."):
                    stack.append((entry, depth + 1))
            elif (
                entry.suffix.lower() in (".html", ".htm")
                and current.name.lower() in _SERVED_UI_DIR_NAMES
            ):
                try:
                    if entry.stat().st_size >= MIN_SERVED_HTML_BYTES:
                        return True
                except OSError:
                    continue
    return False


_BACKEND_HINT_KEYWORDS = (
    "api", "backend", "server", "endpoint", "rest", "gateway", "service",
    "fastapi", "flask", "django", "uvicorn", "webhook", "microservice",
)
_BACKEND_HINT_DEP_MARKERS = ("fastapi", "flask", "django", "uvicorn", "starlette", "aiohttp")

# Analyse 2026-09-16 (syncwave): `frontend_planned` wurde in agents/orchestrator/__init__.py aus
# `any(r.agent_id == "frontend" for r in results)` abgeleitet - also daraus, WELCHE AGENTEN
# TATSAECHLICH LIEFEN. Dieser Wert steuerte aber `ui_ok.required` UND
# `missing_frontend_ui.applicable`: Plante der Planer keinen frontend-Agenten ein, schalteten
# sich genau die beiden Kriterien ab, die einen fehlenden oder kaputten Frontend-Teil finden
# sollen. Der Waechter deaktivierte sich also in exakt dem Fall, fuer den er gebaut wurde.
#
# Realer Beleg: syncwave ("FastAPI-Log-Monitoring-Plattform mit WebSocket-Dashboard") scheiterte
# hart am Browser-UI-Check (WebSocket-Handshake ohne 'Connection'-Header) und bekam ein
# Verifikations-Veto - aber `ui_ok` stand auf `required=False`, weil kein frontend-Agent lief.
# Ergebnis auf der Platte: `is_done: true, blocking: []` trotz gescheiterter Oberflaeche.
#
# Die Erwartung "hier gehoert eine Oberflaeche dazu" stammt deshalb jetzt zusaetzlich aus dem
# Auftragstext. Kurze Token stehen bewusst mit Wortgrenzen in der Liste: "ui" als reine
# Teilzeichenkette trifft sonst "build", "requirements" oder "guide".
_FRONTEND_REQUEST_KEYWORDS = (
    "frontend", "dashboard", "oberfläche", "oberflaeche", "web-app", "webapp", "web app",
    "single-page", "browser", "benutzeroberfläche", "benutzeroberflaeche",
    "svelte", "tailwind", "dark mode", "responsive",
    "diagramm", "formular", "login-screen", "ui/ux",
)
# Nur mit Wortgrenze pruefbar: als reine Teilzeichenkette trifft "lit" sonst "sqlite",
# "spa" trifft "spalte", "ui" trifft "build"/"requirements"/"guide" und "chart" trifft "charta".
_FRONTEND_REQUEST_WORDS = (
    "ui", "html", "css", "seite", "seiten", "lit", "spa", "react", "vue", "chart", "charts",
)
_FRONTEND_REQUEST_WORD_RE = re.compile(
    r"(?<![\w])(" + "|".join(_FRONTEND_REQUEST_WORDS) + r")(?![\w])", re.IGNORECASE,
)


# Analyse EventForge-Lauf (entwickle_eventforge_ein_webhook, 20260916_154524): der Auftrag
# ("...Dark-Mode-Dashboard...") UND der eigene `task_summary` des Laufs ("EventForge
# Webhook-Gateway und Dark-Mode-Dashboard implementiert") nannten Dark-Mode explizit - das
# ausgelieferte Dashboard hatte keine einzige Dark-Mode-Referenz (weißer Hintergrund, kein
# `prefers-color-scheme`, keine `dark`-Klasse). Kein bisheriges Kriterium prüft, ob ein im
# Auftragstext EXPLIZIT benanntes visuelles Merkmal tatsächlich geliefert wurde - `ui_ok`
# (Browser-Check) prüft nur, ob die Seite fehlerfrei RENDERT, nicht WELCHE Merkmale sie zeigt.
_DARK_MODE_REQUEST_RE = re.compile(r"dark[\s-]?mode|dunkel[\s-]?modus|dunkles?\s+design", re.IGNORECASE)
_DARK_MODE_SIGNAL_RE = re.compile(
    r"prefers-color-scheme|data-theme\s*=\s*[\"']dark|class\s*=\s*[\"'][^\"']*\bdark\b"
    r"|\.dark(?:-mode|-theme)?\s*\{|darkMode|dark-theme",
    re.IGNORECASE,
)
_DARK_MODE_SCAN_EXTENSIONS = (".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue")


def _requires_dark_mode(user_request: str, task_summary: str = "") -> bool:
    """Erkennt, ob der Auftrag (oder die eigene Zusammenfassung des Laufs) Dark-Mode explizit
    benennt - unabhängig davon, ob ein Agent es tatsächlich umgesetzt hat."""
    text = f"{user_request or ''} {task_summary or ''}"
    return bool(_DARK_MODE_REQUEST_RE.search(text))


def _has_dark_mode_signal(project_dir: Path, max_files: int = 500) -> bool:
    """True, wenn irgendeine Frontend-Datei ein erkennbares Dark-Mode-Signal enthält
    (`prefers-color-scheme`, eine `dark`-CSS-Klasse/-Regel, `data-theme="dark"`, ...)."""
    seen = 0
    for f in project_dir.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in _DARK_MODE_SCAN_EXTENSIONS:
            continue
        if any(part in _SERVED_UI_SKIP_DIRS or part.startswith(".") for part in f.relative_to(project_dir).parts):
            continue
        seen += 1
        if seen > max_files:
            return False
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _DARK_MODE_SIGNAL_RE.search(text):
            return True
    return False


def _requires_frontend_ui(user_request: str, project_dir: Path) -> bool:
    """
    Erkennt, ob zu diesem Auftrag eine Oberflaeche gehoert - unabhaengig davon, ob ein
    frontend-Agent eingeplant war oder Erfolg hatte.

    Zwei Belege gelten: der Auftragstext nennt eine Oberflaeche, oder im Projekt ist bereits
    eine rein clientseitige Frontend-Abhaengigkeit deklariert (dann war ein Frontend
    unstrittig gewollt, auch wenn die Dateien fehlen).
    """
    text = (user_request or "").lower()
    if any(kw in text for kw in _FRONTEND_REQUEST_KEYWORDS):
        return True
    if text and _FRONTEND_REQUEST_WORD_RE.search(text):
        return True
    pkg_json = Path(project_dir) / "package.json"
    if pkg_json.is_file():
        try:
            inhalt = pkg_json.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            return False
        return any(marker in inhalt for marker in _FRONTEND_ONLY_DEP_MARKERS)
    return False
_BACKEND_HINT_JS_MARKERS = ("express", "fastify", "koa", "nestjs", "@nestjs/core")
_FRONTEND_ONLY_DEP_MARKERS = ("lit", "react", "vue", "svelte")
_PYTHON_BACKEND_FILE_CANDIDATES = (
    "main.py", "app.py", "run.py", "server.py", "wsgi.py", "asgi.py",
    "app/main.py", "app/app.py", "src/main.py", "backend/main.py", "backend/app.py",
    "backend/app/main.py",
)


# Team-Goal (20260913, Aufgabe 1): leichtgewichtige Kandidatenliste für die PROAKTIVE
# Pre-Flight-Prüfung check_entrypoint_exists() unten - bewusst eine eigene, etwas breitere
# Liste als _ENTRYPOINT_CANDIDATES oben (die nur Backend-/API-Projekte betrifft): diese Prüfung
# läuft für JEDES Projekt mit Quelldateien direkt nach Phase 3 (Software-Entwicklung), lange
# bevor build_definition_of_done() am Ende überhaupt weiß, ob ein Backend gebraucht wird.
_LIGHTWEIGHT_PY_ENTRYPOINT_CANDIDATES = (
    "main.py", "app/main.py", "app.py", "src/main.py", "__main__.py", "wsgi.py", "asgi.py",
)
_LIGHTWEIGHT_WEB_ENTRYPOINT_CANDIDATES = (
    "index.html", "src/main.ts", "src/main.js", "ui-src/main.ts", "src/index.ts", "src/index.js",
    "server.js", "app.js", "public/index.html", "static/index.html",
)
_ENTRYPOINT_SCAN_IGNORED_DIRS = frozenset({
    ".git", ".venv", "venv", ".ai_team_venv", "node_modules", "__pycache__", "dist", "build",
})
_ENTRYPOINT_SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx")


def check_entrypoint_exists(project_dir: str | Path) -> tuple[bool, str]:
    """
    Rein lokale, dateibasierte Pre-Flight-Prüfung: existiert bei bereits vorhandenen
    Quelldateien (.py/.ts/.tsx/.js/.jsx) mindestens ein physischer, nicht-leerer
    Haupteinstiegspunkt? Gedacht für den Aufruf DIREKT nach Phase 3 (Software-Entwicklung,
    siehe agents/orchestrator/department.py) - lange bevor QA, Security, Accessibility und
    Review-Phasen Tokens auf einem Zwischenstand verbrennen, der ohnehin nie startet.

    Bewusst kein Ersatz für die spätere, gründlichere `missing_entrypoint`-Prüfung in
    build_definition_of_done() (die zusätzlich erkennt, OB ein Projekt überhaupt einen Server-
    Einstiegspunkt braucht) oder für `_missing_frontend_entrypoints()` in
    core/verifier/completeness.py (die zusätzlich `src/`-Strukturen für Frontend-Projekte
    prüft) - diese Funktion ist absichtlich simpler und billiger, damit sie sich früh und ohne
    LLM-Aufruf im Orchestrator-Loop einschieben lässt.

    Gibt (True, "") zurück, wenn ein Einstiegspunkt existiert ODER das Projekt (noch) gar keine
    Quelldateien enthält (kein Software-Code-Projekt - nichts zu bemängeln). Gibt
    (False, <Begründung>) zurück, wenn Quelldateien existieren, aber kein Startpunkt.
    """
    pfad = Path(project_dir)
    if not pfad.is_dir():
        return True, ""

    has_source_files = any(
        f.is_file() and f.suffix in _ENTRYPOINT_SOURCE_SUFFIXES
        and not any(part in _ENTRYPOINT_SCAN_IGNORED_DIRS for part in f.relative_to(pfad).parts)
        for f in pfad.rglob("*")
    )
    if not has_source_files:
        return True, ""

    for rel in (*_LIGHTWEIGHT_PY_ENTRYPOINT_CANDIDATES, *_LIGHTWEIGHT_WEB_ENTRYPOINT_CANDIDATES):
        kandidat = pfad / rel
        try:
            if kandidat.is_file() and kandidat.stat().st_size > 0:
                return True, ""
        except OSError:
            continue
    return False, (
        "Kein Haupteinstiegspunkt gefunden - es existieren bereits Quelldateien, aber weder "
        "main.py/app/main.py/app.py/src/main.py/__main__.py/wsgi.py/asgi.py (Python) noch "
        "index.html/public/index.html/src/main.ts/src/main.js/ui-src/main.ts/src/index.ts/"
        "src/index.js/server.js/app.js (Web/Node)."
    )


def _find_entrypoint_file(project_dir: Path) -> str | None:
    """Gibt den relativen Pfad des ersten gefundenen Einstiegspunkts zurück - sonst None."""
    for rel in _ENTRYPOINT_CANDIDATES:
        if (project_dir / rel).is_file():
            return rel
    return None


def _requires_backend_entrypoint(project_dir: Path, user_request: str = "") -> bool:
    """
    Erkennt, ob dieses Projekt einen laufenden Server-Einstiegspunkt braucht - entweder weil
    der Auftrag selbst danach klingt (API, Backend, Gateway, ...) oder weil bereits ein
    Web-Framework als Abhängigkeit deklariert wurde.
    """
    pkg_json = project_dir / "package.json"
    pkg_inhalt = ""
    if pkg_json.is_file():
        try:
            pkg_inhalt = pkg_json.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            pkg_inhalt = ""
    hat_js_backend_marker = any(marker in pkg_inhalt for marker in _BACKEND_HINT_JS_MARKERS)

    # Team-Goal (20260913, Aufgabe 1): Realer Fund (ecochef) - ein Projekt mit rein
    # clientseitigen Frontend-Dependencies (Lit/React/Vue/Svelte), OHNE Node-Backend-Marker und
    # OHNE Python-Backend-Dateien, braucht keinen Server-Einstiegspunkt, solange ein
    # Web-Einstiegspunkt (index.html/main.ts/...) existiert - selbst wenn der Auftragstext oder
    # ein Dateiname Wörter wie "service" oder "api" enthält (z.B. "storage.service.ts" bei
    # EcoChef, die den generischen `_BACKEND_HINT_KEYWORDS`-Check unten sonst fälschlich
    # ausgelöst hätten). Diese Erkennung MUSS vor dem Keyword-Check laufen, da genau dieser
    # Check das Problem war.
    if pkg_inhalt and not hat_js_backend_marker and any(
        marker in pkg_inhalt for marker in _FRONTEND_ONLY_DEP_MARKERS
    ):
        hat_python_backend = any(
            (project_dir / rel).is_file() for rel in _PYTHON_BACKEND_FILE_CANDIDATES
        )
        hat_web_entrypoint = any(
            (project_dir / rel).is_file() for rel in _WEB_ENTRYPOINT_CANDIDATES
        )
        if not hat_python_backend and hat_web_entrypoint:
            return False

    if any(kw in user_request.lower() for kw in _BACKEND_HINT_KEYWORDS):
        return True
    for name in ("requirements.txt", "pyproject.toml"):
        kandidat = project_dir / name
        if kandidat.is_file():
            try:
                inhalt = kandidat.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            if any(marker in inhalt for marker in _BACKEND_HINT_DEP_MARKERS):
                return True
    if hat_js_backend_marker:
        return True
    return False


def _has_test_files(project_dir: Path, max_files: int = 5000) -> bool:
    """True, wenn im Projekt mindestens eine Testdatei liegt (Python oder JS/TS)."""
    seen = 0
    for _dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in _TEST_SCAN_IGNORED_DIRS]
        for name in filenames:
            seen += 1
            if seen > max_files:
                return False
            if (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py") or name.endswith(_TEST_FILE_SUFFIXES):
                return True
    return False


def build_definition_of_done(
    project_slug: str,
    project_dir: str | Path,
    *,
    files_written: int,
    tests_ran: bool,
    tests_passed: bool,
    deps_installable: bool | None = None,
    lint_clean: bool | None = None,
    app_starts: bool | None = None,
    secrets_clean: bool | None = None,
    ui_ok: bool | None = None,
    coverage_percent: float | None = None,
    min_coverage: float = 0.0,
    verification_skipped: bool = False,
    verification_ran: bool = False,
    user_request: str = "",
    task_summary: str = "",
    frontend_planned: bool = False,
    build_passes: bool | None = None,
    test_depth_ok: bool | None = None,
    verification_ok: bool | None = None,
    failed_checks: list[str] | None = None,
) -> DefinitionOfDone:
    """
    Setzt die Einzelsignale eines Laufs zu einer Gesamtaussage zusammen.

    `None` bedeutet durchgängig "für dieses Projekt nicht geprüft/nicht anwendbar" - solche
    Kriterien blockieren bewusst nicht. Das ist der Unterschied zu "geprüft und durchgefallen"
    (False), den der bisherige Prosa-Status nie machen konnte.

    Ausnahme davon ist `verification_ran=True`: lief die Verifikations-Pipeline wirklich, dann
    ist ein fehlender Messwert bei einer PFLICHT-Prüfung kein "nicht relevant", sondern ein
    "hätte gemessen werden müssen, wurde es aber nicht" - z.B. weil die Prüfung abgebrochen ist.
    Solche Kriterien blockieren dann und tragen `nicht gemessen` als Detail. Ohne dieses Flag
    (Voreinstellung) bleibt das alte, nachsichtige Verhalten erhalten.

    `verification_ok=False` (Gesamtergebnis der Verifikation) blockiert immer, sofern die
    Verifikation nicht übersprungen wurde - ein Projekt kann nie gleichzeitig "fertig" und
    "Verifikation fehlgeschlagen" sein. `failed_checks` benennt die gescheiterten Prüfungen.
    """
    pfad = Path(project_dir)
    kriterien: list[Criterion] = []

    # Siehe `_requires_frontend_ui()`: `frontend_planned` allein sagt nur, WELCHE AGENTEN LIEFEN,
    # und schaltete damit genau die Frontend-Waechter ab, wenn kein frontend-Agent eingeplant war.
    # Die Erwartung stammt deshalb zusaetzlich aus dem Auftragstext bzw. aus bereits deklarierten
    # Frontend-Abhaengigkeiten im Projekt.
    frontend_erwartet = frontend_planned or _requires_frontend_ui(user_request, pfad)

    # Analyse 2026-09-16: `applicable=<wert> is not None` behandelte "nicht gemessen" wie "nicht
    # relevant". Fuer die Pflichtpruefungen unten ist das genau falsch, sobald die Verifikation
    # tatsaechlich lief: `core/verification_outcome.py` liefert `status() is None` sowohl fuer
    # bewusst uebersprungene ALS AUCH fuer nie aufgezeichnete Pruefungen (z.B. nach einem Abbruch).
    # Eine abgebrochene Installations- oder Startpruefung wurde dadurch stillschweigend zu
    # "fertig". Lief die Pipeline, gilt ein fehlender Messwert deshalb als Blocker.
    # Ein fehlender Messwert blockiert aber nur dort, wo die Messung ueberhaupt geschuldet war:
    # `smoke` wird bewusst nicht aufgezeichnet, wenn es keinen startbaren Einstiegspunkt gibt, und
    # `deps_install` nicht, wenn es keine Abhaengigkeitsdatei zu installieren gibt. Diese beiden
    # Faelle sind echte "nicht anwendbar" und duerfen nicht zu Blockern werden.
    fehlmessung_blockt = verification_ran and not verification_skipped
    hat_dependency_manifest = any(
        (pfad / name).is_file()
        for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
                     "Pipfile", "package.json")
    )

    def _gemessen(wert: bool | None, geschuldet: bool) -> tuple[bool, str]:
        """
        Liefert (applicable, detail) fuer eine Pflichtpruefung. Fehlt der Messwert, obwohl die
        Pipeline lief und die Pruefung fuer dieses Projekt faellig war, wird das Kriterium
        anwendbar - und damit (weil `passed=False`) zum Blocker.
        """
        if wert is not None:
            return True, ""
        if fehlmessung_blockt and geschuldet:
            return True, "nicht gemessen - die Prüfung lief nicht zu Ende"
        return False, ""

    # Das grundlegendste Kriterium überhaupt - und genau das, was im Lauf event_ticket_api
    # fehlte, ohne dass der Projektstatus es benannt hätte.
    kriterien.append(Criterion(
        key="files_written",
        label="Es wurde tatsächlich Code erzeugt",
        passed=files_written > 0,
        detail=f"{files_written} Datei(en) geschrieben",
    ))

    # Realer Fund (auditlog_sentinel, 2026-09-10): Nach einem Budget-Abbruch meldete die DoD
    # "keine ausführbaren Tests gefunden", obwohl tests/test_api.py existierte – die Verifikation
    # war nur übersprungen worden. Übersprungen und "nicht vorhanden" sind verschiedene Befunde.
    #
    # Weiterer Fund (toggleforge, 2026-09-12): `tests_on_disk` war zusätzlich an
    # `verification_skipped` gekoppelt. Lief die Verifikation regulär durch (verification_skipped
    # = False), wurde `tests_on_disk` IMMER False, selbst wenn Testdateien vorhanden waren. Ob
    # Testdateien auf der Platte liegen, ist aber unabhängig davon, ob der Lauf abgebrochen wurde.
    tests_on_disk = _has_test_files(pfad)
    if tests_ran:
        exist_detail = ""
    elif tests_on_disk:
        exist_detail = (
            "Testdateien vorhanden, aber nicht ausgeführt (Lauf vorzeitig abgebrochen)"
            if verification_skipped else "Testdateien auf Festplatte vorhanden"
        )
    elif verification_skipped:
        exist_detail = "nicht geprüft (Lauf vorzeitig abgebrochen)"
    else:
        exist_detail = "keine ausführbaren Tests gefunden"
    kriterien.append(Criterion(
        key="tests_exist",
        label="Eine echte Testsuite existiert",
        passed=bool(tests_ran or tests_on_disk),
        detail=exist_detail,
    ))
    if tests_passed:
        pass_detail = ""
    elif verification_skipped and not tests_ran:
        pass_detail = "nicht ausgeführt (Lauf vorzeitig abgebrochen)"
    else:
        pass_detail = "Tests fehlgeschlagen oder nicht gelaufen"
    kriterien.append(Criterion(
        key="tests_pass",
        label="Die Testsuite läuft grün",
        passed=bool(tests_ran and tests_passed),
        detail=pass_detail,
    ))

    kriterien.append(Criterion(
        key="deps_installable",
        label="Abhängigkeiten sind installierbar",
        passed=bool(deps_installable),
        applicable=_gemessen(deps_installable, hat_dependency_manifest)[0],
        detail=_gemessen(deps_installable, hat_dependency_manifest)[1],
    ))
    kriterien.append(Criterion(
        key="app_starts",
        label="Die Anwendung startet",
        passed=bool(app_starts),
        applicable=_gemessen(app_starts, _find_entrypoint_file(pfad) is not None)[0],
        detail=_gemessen(app_starts, _find_entrypoint_file(pfad) is not None)[1],
    ))
    kriterien.append(Criterion(
        key="secrets_clean",
        label="Keine Secrets im Code",
        passed=bool(secrets_clean),
        applicable=secrets_clean is not None,
    ))
    # Lint ist bewusst NICHT verpflichtend: Ein Stilverstoß macht ein Projekt nicht unfertig.
    kriterien.append(Criterion(
        key="lint_clean",
        label="Linter ohne Befund",
        passed=bool(lint_clean),
        required=False,
        applicable=lint_clean is not None,
    ))
    # Realer Fund (toggleforge, 2026-09-12): ein fehlgeschlagener Frontend/UI-Check (z.B. ein
    # fehlendes statisches Asset wie static/app.js) setzte bislang das GESAMTE verification_ok
    # zurück und ließ dadurch eine tatsächlich grüne Backend-Unit-Testsuite als "nicht gelaufen"
    # bzw. "nicht bestanden" erscheinen (siehe tests_ran/tests_passed oben, die inzwischen direkt
    # am Testsuite-Treffer im Summary hängen statt am kaskadierten verification_ok). Der UI-Status
    # bekommt hier ein EIGENES, nicht-verpflichtendes Kriterium, damit er sichtbar bleibt, ohne
    # die Backend-Testsuite mit in den Abgrund zu ziehen.
    # Für ein beauftragtes Frontend ist ein fehlgeschlagener UI-Check ein echter Mangel (die
    # Oberfläche funktioniert nicht) - nur wo gar keine Oberfläche beauftragt war, bleibt er ein
    # Hinweis.
    kriterien.append(Criterion(
        key="ui_ok",
        label="Frontend/UI-Check ohne Befund",
        passed=bool(ui_ok),
        required=frontend_erwartet,
        applicable=ui_ok is not None,
    ))
    kriterien.append(Criterion(
        key="test_depth",
        label="Die API-Routen werden in Tests tatsächlich aufgerufen",
        passed=bool(test_depth_ok),
        applicable=test_depth_ok is not None,
        detail="" if test_depth_ok is not False else "zu viele Backend-Routen ohne Test (core/test_depth.py)",
    ))
    kriterien.append(Criterion(
        key="build_passes",
        label="Der Produktions-Build läuft durch",
        passed=bool(build_passes),
        applicable=build_passes is not None,
        detail="" if build_passes is not False else "Frontend-/Produktions-Build fehlgeschlagen",
    ))
    # `/goal`-Auftrag (20260915, Schwachstelle 2): das bisherige `ui_ok`-Kriterium oben ist nur
    # dann `applicable`, wenn der Browser-UI-Check überhaupt LIEF - und der überspringt sich
    # selbst mangels servierbarer index.html genau dann, wenn der frontend-Agent am Hard
    # Delivery Gate scheiterte (agents/base_agent.py: "keine einzige Datei über write_file/
    # edit_file gespeichert"). Ein komplett ausgefallenes Frontend blieb dadurch unbemerkt -
    # `ui_ok=None` ("nicht anwendbar") statt eines echten, blockierenden Befunds. Dieses
    # Kriterium prüft NUR dateibasiert (kein LLM/Browser nötig) und ist ausschließlich
    # `applicable`, wenn zu diesem Auftrag ueberhaupt eine Oberflaeche gehoert
    # (`frontend_erwartet`) - ein Projekt ohne beauftragtes Frontend blockiert dadurch nie.
    hat_web_entrypoint_datei = (
        any((pfad / rel).is_file() for rel in _WEB_ENTRYPOINT_CANDIDATES) or has_served_html_ui(pfad)
    )
    kriterien.append(Criterion(
        key="missing_frontend_ui",
        label="Beauftragtes Frontend wurde tatsächlich geliefert",
        passed=hat_web_entrypoint_datei,
        applicable=frontend_erwartet,
        detail=(
            "" if hat_web_entrypoint_datei or not frontend_erwartet
            else "kein index.html/src/main.tsx/... gefunden - Frontend-Agent ist am Hard "
                 "Delivery Gate gescheitert oder hat keine UI-Dateien geschrieben"
        ),
    ))
    # Explizit im Auftrag benannte visuelle Merkmale (aktuell: Dark-Mode) - siehe Modul-Docstring
    # dieses Abschnitts oben für den realen Fund. Nur `applicable`, wenn der Auftragstext (oder
    # die eigene Zusammenfassung des Laufs) Dark-Mode wirklich nennt UND überhaupt ein Frontend
    # erwartet wird - ein reines Backend-Projekt mit "dark" irgendwo im Freitext soll nicht
    # blockieren.
    dark_mode_erwartet = frontend_erwartet and _requires_dark_mode(user_request, task_summary)
    hat_dark_mode = dark_mode_erwartet and _has_dark_mode_signal(pfad)
    kriterien.append(Criterion(
        key="dark_mode_delivered",
        label="Explizit beauftragtes Dark-Mode-Design wurde geliefert",
        passed=hat_dark_mode,
        applicable=dark_mode_erwartet,
        detail=(
            "" if hat_dark_mode or not dark_mode_erwartet
            else "Auftrag nennt Dark-Mode, aber keine Frontend-Datei enthält ein erkennbares "
                 "Dark-Mode-Signal (prefers-color-scheme, dark-Klasse/-CSS-Regel, data-theme=\"dark\")"
        ),
    ))

    if min_coverage > 0:
        erreicht = coverage_percent is not None and coverage_percent >= min_coverage
        kriterien.append(Criterion(
            key="coverage",
            label=f"Testabdeckung ≥ {min_coverage:.0f}%",
            passed=erreicht,
            required=False,
            applicable=coverage_percent is not None,
            detail=f"{coverage_percent:.1f}%" if coverage_percent is not None else "nicht gemessen",
        ))

    # Realer Fund pulseflow_gateway: grüne Tests + README + ADRs, aber NULL Anwendungscode.
    # Ein Backend-/API-Projekt ohne main.py/app.py/... ist NIE fertig - unabhängig davon, ob
    # irgendwelche Smoke-Tests grün liefen.
    braucht_entrypoint = _requires_backend_entrypoint(pfad, user_request)
    gefundener_entrypoint = _find_entrypoint_file(pfad)
    kriterien.append(Criterion(
        key="missing_entrypoint",
        label="Ein echter Anwendungs-Einstiegspunkt existiert",
        passed=gefundener_entrypoint is not None,
        applicable=braucht_entrypoint,
        detail=(
            f"gefunden: {gefundener_entrypoint}" if gefundener_entrypoint
            else "kein main.py/app.py/run.py/... gefunden - nur Doku/Tests ohne Anwendungscode" if braucht_entrypoint
            else ""
        ),
    ))

    if not verification_skipped and (verification_ok is not None or fehlmessung_blockt):
        offene_checks = ", ".join(failed_checks or [])
        kriterien.append(Criterion(
            key="verification_ok",
            label="Die Gesamt-Verifikation ist ohne Veto",
            passed=bool(verification_ok),
            detail="" if verification_ok else (
                "kein Gesamtergebnis der Verifikation vorhanden - die Pipeline lief, "
                "hat aber kein Urteil hinterlassen" if verification_ok is None else
                f"fehlgeschlagene Prüfungen: {offene_checks}" if offene_checks
                else "mindestens eine Verifikations-Prüfung ist fehlgeschlagen"
            ),
        ))

    # README als Mindestmaß an Übergabefähigkeit - ein Projekt, das niemand benutzen kann, ist
    # nicht fertig, aber ein fehlendes README blockiert die Auslieferung nicht.
    hat_readme = any((pfad / name).exists() for name in ("README.md", "readme.md", "README.rst"))
    kriterien.append(Criterion(
        key="readme",
        label="README vorhanden",
        passed=hat_readme,
        required=False,
    ))

    return DefinitionOfDone(
        project_slug=project_slug,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        criteria=kriterien,
    )


def write_definition_of_done(project_dir: str | Path, dod: DefinitionOfDone) -> Path | None:
    """Schreibt `.ai_team_dod.json`. Gibt den Pfad zurück - None, wenn das Schreiben scheitert."""
    ziel = Path(project_dir) / DOD_FILENAME
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(
            json.dumps(dod.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8",
        )
        return ziel
    except OSError:
        return None


def read_definition_of_done(project_dir: str | Path) -> dict | None:
    """Liest `.ai_team_dod.json` - None, wenn die Datei fehlt oder beschädigt ist."""
    quelle = Path(project_dir) / DOD_FILENAME
    try:
        return json.loads(quelle.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
