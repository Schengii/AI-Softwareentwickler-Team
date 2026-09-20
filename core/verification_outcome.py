"""
core/verification_outcome.py – Strukturiertes Ergebnis aller Verifikations-Prüfungen eines Laufs.

Bisher leiteten nachgelagerte Konsumenten (Definition of Done, Projektstatus) den Zustand
einzelner Prüfungen per Textsuche aus dem Markdown-Verifikationsprotokoll ab (z. B.
`"Testsuite bestanden" in verification_summary`). Das brach still, sobald sich ein
Meldungstext änderte – `ui_ok` konnte so nie `True` werden, weil das Protokoll
"Frontend/UI-Check: … fehlerfrei" statt der gesuchten Formulierung schrieb.

`VerificationOutcome` hält pro Prüfung einen expliziten Status (`passed`/`failed`/`skipped`).
Das Markdown-Protokoll bleibt reine Darstellung.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

CheckStatus = Literal["passed", "failed", "skipped"]

# Kanonische Schlüssel - Tippfehler in Aufrufern sollen sofort auffallen statt still ein
# neues, nie gelesenes Feld anzulegen.
CHECK_KEYS: frozenset[str] = frozenset({
    "pre_flight",
    "deps_install",
    "import_check",
    "tests",
    "test_depth",
    "test_regression",
    "docker_build",
    "frontend_build",
    "dependency_audit",
    "sast",
    "license",
    "lint",
    "completeness",
    "coverage",
    "smoke",
    "load_test",
    "browser_ui",
    "accessibility",
    "interface_fields",
    "security_handoff",
})

# Prüfungen, die ein Ergebnis MELDEN, aber `verification_ok` bewusst NICHT beeinflussen.
# Lag bis 2026-09-20 in agents/orchestrator/verification_checks.py und wird von dort
# weiterhin re-exportiert; die Einteilung "blockierend vs. informativ" ist aber eine
# Eigenschaft der Prüfung selbst und gehört deshalb neben CHECK_KEYS - sonst kann
# `VerificationOutcome` selbst nicht sagen, welche seiner Fehlschläge etwas bedeuten
# (Schichtung: core darf nicht aus agents importieren).
INFORMATIONAL_CHECK_KEYS: frozenset[str] = frozenset({
    "dependency_audit", "sast", "license", "lint", "accessibility", "interface_fields",
})


@dataclass
class CheckResult:
    """Ergebnis einer einzelnen Prüfung."""

    status: CheckStatus
    detail: str = ""


@dataclass
class VerificationOutcome:
    """Sammelt die Ergebnisse aller Prüfungen eines Verifikationslaufs."""

    checks: dict[str, CheckResult] = field(default_factory=dict)
    skipped_reason: str = ""

    def record(self, key: str, passed: bool | None, detail: str = "") -> None:
        """Hält das Ergebnis einer Prüfung fest. `passed=None` bedeutet übersprungen.

        Eine spätere Meldung derselben Prüfung überschreibt die frühere (z. B. Testsuite
        nach einem erfolgreichen Fixversuch).
        """
        if key not in CHECK_KEYS:
            raise KeyError(f"Unbekannter Verifikations-Check: {key!r}")
        status: CheckStatus = "skipped" if passed is None else ("passed" if passed else "failed")
        self.checks[key] = CheckResult(status=status, detail=str(detail or "")[:500])

    def status(self, key: str) -> bool | None:
        """True = bestanden, False = fehlgeschlagen, None = nicht gelaufen/übersprungen."""
        result = self.checks.get(key)
        if result is None or result.status == "skipped":
            return None
        return result.status == "passed"

    def ran(self, key: str) -> bool:
        return self.status(key) is not None

    @property
    def failed_checks(self) -> list[str]:
        return sorted(k for k, r in self.checks.items() if r.status == "failed")

    @property
    def blocking_failed_checks(self) -> list[str]:
        """Nur die fehlgeschlagenen Prüfungen, die `verification_ok` tatsächlich blockieren.

        Realer Fund (Roadmap P0-6, 2026-09-20): `lint` stand in 5 von 6 der letzten Läufe in
        `failed`, obwohl es informativ ist und `verification_ok` laut
        `reconcile_verification_ok()` nie beeinflusst. Jeder Konsument von `failed_checks`
        las das trotzdem als echten Fehlschlag - die Definition of Done nannte bei
        cachegrid_proxy "fehlgeschlagene Prüfungen: lint, pre_flight", obwohl allein
        `pre_flight` blockierte, und der Root-Cause-Analyst verbrannte eine vollständige,
        werkzeugbasierte Tiefenanalyse für eine ungenutzte Variable (ruff F841).
        """
        return sorted(k for k in self.failed_checks if k not in INFORMATIONAL_CHECK_KEYS)

    @property
    def informational_failed_checks(self) -> list[str]:
        """Gegenstück zu `blocking_failed_checks`: gemeldet, aber ohne Einfluss auf das Urteil."""
        return sorted(k for k in self.failed_checks if k in INFORMATIONAL_CHECK_KEYS)

    def to_dict(self) -> dict:
        return {
            "checks": {k: asdict(v) for k, v in sorted(self.checks.items())},
            "failed": self.failed_checks,
            # Getrennt ausgewiesen, damit Berichte und spätere Analysen den blockierenden
            # Grund vom bloßen Hinweis unterscheiden können. `failed` bleibt unverändert -
            # bestehende Leser (u.a. core/project_status.py) sollen nicht brechen.
            "failed_blocking": self.blocking_failed_checks,
            "failed_informational": self.informational_failed_checks,
            "skipped_reason": self.skipped_reason,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> VerificationOutcome:
        outcome = cls()
        if not isinstance(data, dict):
            return outcome
        outcome.skipped_reason = str(data.get("skipped_reason") or "")
        for key, raw in (data.get("checks") or {}).items():
            if key in CHECK_KEYS and isinstance(raw, dict) and raw.get("status") in ("passed", "failed", "skipped"):
                outcome.checks[key] = CheckResult(status=raw["status"], detail=str(raw.get("detail") or ""))
        return outcome


def parse_install_exit_code(install_log: str) -> int | None:
    """Liest `exit_code=N` aus dem Installations-Log von `ProjectVerifier.ensure_environment()`.

    Mehrere Installationen (pip + npm) -> der schlechteste (höchste) Exit-Code zählt.
    """
    import re

    if not isinstance(install_log, str):
        return None
    codes = [int(m) for m in re.findall(r"exit_code=(-?\d+)", install_log)]
    if not codes:
        return None
    non_zero = [c for c in codes if c != 0]
    return non_zero[0] if non_zero else 0
