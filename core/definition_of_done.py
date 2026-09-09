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
    coverage_percent: float | None = None,
    min_coverage: float = 0.0,
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

    kriterien.append(Criterion(
        key="tests_exist",
        label="Eine echte Testsuite existiert",
        passed=tests_ran,
        detail="" if tests_ran else "keine ausführbaren Tests gefunden",
    ))
    kriterien.append(Criterion(
        key="tests_pass",
        label="Die Testsuite läuft grün",
        passed=bool(tests_ran and tests_passed),
        detail="" if tests_passed else "Tests fehlgeschlagen oder nicht gelaufen",
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
