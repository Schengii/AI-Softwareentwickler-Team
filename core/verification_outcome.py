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

    def to_dict(self) -> dict:
        return {
            "checks": {k: asdict(v) for k, v in sorted(self.checks.items())},
            "failed": self.failed_checks,
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
