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
)
_BACKEND_HINT_KEYWORDS = (
    "api", "backend", "server", "endpoint", "rest", "gateway", "service",
    "fastapi", "flask", "django", "uvicorn", "webhook", "microservice",
)
_BACKEND_HINT_DEP_MARKERS = ("fastapi", "flask", "django", "uvicorn", "starlette", "aiohttp")
_BACKEND_HINT_JS_MARKERS = ("express", "fastify", "koa", "nestjs", "@nestjs/core")


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
    pkg_json = project_dir / "package.json"
    if pkg_json.is_file():
        try:
            inhalt = pkg_json.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            inhalt = ""
        if any(marker in inhalt for marker in _BACKEND_HINT_JS_MARKERS):
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
    user_request: str = "",
) -> DefinitionOfDone:
    """
    Setzt die Einzelsignale eines Laufs zu einer Gesamtaussage zusammen.

    `None` bedeutet durchgängig "für dieses Projekt nicht geprüft/nicht anwendbar" - solche
    Kriterien blockieren bewusst nicht. Das ist der Unterschied zu "geprüft und durchgefallen"
    (False), den der bisherige Prosa-Status nie machen konnte.
    """
    pfad = Path(project_dir)
    kriterien: list[Criterion] = []

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
        applicable=deps_installable is not None,
    ))
    kriterien.append(Criterion(
        key="app_starts",
        label="Die Anwendung startet",
        passed=bool(app_starts),
        applicable=app_starts is not None,
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
    kriterien.append(Criterion(
        key="ui_ok",
        label="Frontend/UI-Check ohne Befund",
        passed=bool(ui_ok),
        required=False,
        applicable=ui_ok is not None,
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
