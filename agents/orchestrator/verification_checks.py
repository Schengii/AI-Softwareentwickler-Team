"""
agents/orchestrator/verification_checks.py – Informative Verifikations-Prüfschritte als Pipeline.

Erster Schritt der Aufteilung von `_run_verification_loop_impl()` (verification.py, eine einzelne
Methode mit ~1.400 Zeilen): Prüfungen, die KEINE Fix-Agenten beauftragen und `verification_ok`
nicht beeinflussen, sind hier eigenständige, einzeln testbare Schritte mit einheitlicher
Schnittstelle. Jeder Schritt schreibt sein Ergebnis strukturiert in `VerificationOutcome`
(core/verification_outcome.py) und menschenlesbar in das Protokoll.

Hintergrund der einzelnen Prüfungen: Sie ersetzen frühere LLM-Freitext-Einschätzungen der
Rollen security/compliance durch echte Werkzeuge (pip-audit/npm audit, bandit, pip-licenses,
ruff/ESLint/tsc) - siehe CHANGELOG.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from core.verification_outcome import VerificationOutcome


@dataclass
class CheckContext:
    """Gemeinsamer Zustand, den jeder Prüfschritt liest und ergänzt."""

    verifier: object
    outcome: VerificationOutcome
    notify: Callable[[str], None]
    summary_lines: list[str] = field(default_factory=list)
    lint_signature: list[str] = field(default_factory=list)
    lint_attempted: bool = False


def _top(items: list, render: Callable[[object], str], limit: int = 5) -> str:
    text = "; ".join(render(i) for i in items[:limit])
    if len(items) > limit:
        text += f" … und {len(items) - limit} weitere"
    return text


def _record_first_failure(outcome: VerificationOutcome, key: str, passed: bool, detail: str = "") -> None:
    """Mehrere Reports (z. B. pip + npm) - ein Fehlschlag darf nicht von einem späteren Erfolg überschrieben werden."""
    if outcome.status(key) is not False:
        outcome.record(key, passed, detail)


async def check_dependency_audit(ctx: CheckContext) -> None:
    """Abgleich der Abhängigkeiten gegen öffentliche Advisory-Datenbanken. Ein technisch nicht
    durchführbarer Scan (Tool/Netzwerk fehlt) gilt als nicht geprüft, nie als "sauber"."""
    for audit in await asyncio.to_thread(ctx.verifier.check_dependency_vulnerabilities):
        if not audit.attempted:
            continue
        count = len(audit.vulnerabilities)
        _record_first_failure(ctx.outcome, "dependency_audit", not audit.vulnerable, f"{audit.tool}: {count} Schwachstelle(n)" if audit.vulnerable else "")
        if audit.vulnerable:
            top = _top(audit.vulnerabilities, lambda v: f"{v.package} {v.version} ({v.vulnerability_id})")
            ctx.notify(f"  🔓 [bold red]{audit.tool}: {count} bekannte Schwachstelle(n) in Abhängigkeiten.[/bold red]")
            ctx.summary_lines.append(f"- 🔓 ❌ {audit.tool}: {count} bekannte Schwachstelle(n) in Abhängigkeiten: {top}")
        else:
            ctx.notify(f"  🔒 [bold green]{audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten.[/bold green]")
            ctx.summary_lines.append(f"- 🔒 {audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten gefunden.")


async def check_sast(ctx: CheckContext) -> None:
    """Statischer Sicherheits-Scan des eigenen Codes - informativ (Funde können False Positives sein)."""
    for sast in await asyncio.to_thread(ctx.verifier.check_sast):
        if not sast.attempted:
            continue
        count = len(sast.findings)
        _record_first_failure(ctx.outcome, "sast", not sast.vulnerable, f"{count} Fund(e)" if sast.vulnerable else "")
        if sast.vulnerable:
            top = _top(sast.findings, lambda f: f"{f.file_path}:{f.line_number} [{f.rule}/{f.severity}]")
            ctx.notify(f"  🕵️ [bold red]{sast.tool}: {count} potenzielle Sicherheits-Fund(e) im Code.[/bold red]")
            ctx.summary_lines.append(f"- 🕵️ ⚠️ {sast.tool}: {count} potenzielle Sicherheits-Fund(e) im Code: {top}")
        else:
            ctx.notify(f"  🕵️ [bold green]{sast.tool}: keine Sicherheits-Funde im Code.[/bold green]")
            ctx.summary_lines.append(f"- 🕵️ {sast.tool}: keine Sicherheits-Funde im Code (statischer Scan).")


async def check_licenses(ctx: CheckContext) -> None:
    """Lizenz-Scan der installierten Pakete - Copyleft ist eine rechtliche Einschätzungsfrage."""
    for lic in await asyncio.to_thread(ctx.verifier.check_licenses):
        if not lic.attempted:
            continue
        _record_first_failure(ctx.outcome, "license", not lic.has_copyleft_risk)
        if lic.has_copyleft_risk:
            copyleft = [f for f in lic.findings if f.copyleft]
            top = _top(copyleft, lambda f: f"{f.package} {f.version} ({f.license})")
            ctx.notify(f"  📜 [bold red]{lic.tool}: {len(copyleft)} Copyleft-Lizenz(en) in Abhängigkeiten (GPL/LGPL/MPL/…).[/bold red]")
            ctx.summary_lines.append(f"- 📜 ⚠️ {lic.tool}: {len(copyleft)} Copyleft-Lizenz(en) in Abhängigkeiten: {top}")
        else:
            ctx.notify(f"  📜 [bold green]{lic.tool}: keine Copyleft-Lizenzen in Abhängigkeiten.[/bold green]")
            ctx.summary_lines.append(f"- 📜 {lic.tool}: keine Copyleft-Lizenzen in Abhängigkeiten gefunden ({len(lic.findings)} geprüft).")


async def check_lint(ctx: CheckContext) -> None:
    """Lint für generierten Code. `lint_signature` ("tool:datei:regel") erkennt über mehrere Läufe
    bestehende Funde; `lint_attempted` verhindert, dass ein übersprungener Lint als behoben gilt."""
    for lint in await asyncio.to_thread(ctx.verifier.check_lint):
        if not lint.attempted:
            continue
        ctx.lint_attempted = True
        count = len(lint.issues)
        _record_first_failure(ctx.outcome, "lint", lint.passed, "" if lint.passed else f"{lint.tool}: {count} Fund(e)")
        ctx.lint_signature.extend(f"{lint.tool}:{i.file_path}:{i.rule}" for i in lint.issues)
        if not lint.passed:
            top = _top(lint.issues, lambda i: f"{i.file_path}:{i.line_number} [{i.rule}]")
            ctx.notify(f"  🎨 [bold yellow]{lint.tool}: {count} Lint-Fund(e).[/bold yellow]")
            ctx.summary_lines.append(f"- 🎨 ⚠️ {lint.tool}: {count} Lint-Fund(e): {top}")
        else:
            ctx.notify(f"  🎨 [bold green]{lint.tool}: keine Lint-Funde.[/bold green]")
            ctx.summary_lines.append(f"- 🎨 {lint.tool}: keine Lint-Funde.")


# Reihenfolge der informativen Schritte (nach Build, vor Vollständigkeit/Coverage/Laufzeit).
INFORMATIONAL_CHECKS: tuple[Callable[[CheckContext], object], ...] = (
    check_dependency_audit,
    check_sast,
    check_licenses,
    check_lint,
)


async def run_informational_checks(ctx: CheckContext) -> CheckContext:
    for step in INFORMATIONAL_CHECKS:
        await step(ctx)
    return ctx
