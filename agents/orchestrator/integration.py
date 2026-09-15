"""
agents/orchestrator/integration.py – IntegrationMixin: Gerüst vor und Integrations-Checkpoint
nach der Entwicklungsphase.

Echte Teams integrieren kontinuierlich: Code, der sich nicht importieren lässt, geht nicht in
Review, Doku oder QA. Bisher lief die erste echte Prüfung erst NACH allen sechs Fachbereichen -
Content-, QA- und Governance-Agenten bauten dadurch auf kaputtem Code auf, und die Funde
(bis zu 20 Pre-Flight-Probleme pro Lauf) kosteten am Ende mehrere Fix-Runden.

- `_apply_project_scaffold()`: deterministisches Gerüst (core/project_scaffold.py) direkt vor
  der Entwicklungsphase.
- `_run_integration_checkpoint()`: direkt nach der Entwicklungsphase Pre-Flight-Check +
  deterministische Autofixes (fehlende `__init__.py`, fehlende Pakete) + genau EINE gezielte
  Fix-Runde für die verbleibenden statischen Befunde an die Datei-Owner.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from config import ENABLE_CONTRACT_REVIEW, ENABLE_TEAM_BOARD
from core.contract_verifier import normalize_path, verify_api_contracts
from core.decision_log import log_decision
from core.dependency_manifest import add_requirement, manifest_for_package, package_from_finding
from core.message_bus import AgentResult, AgentTask
from core.pre_flight_check import run_pre_flight_check
from core.project_scaffold import ScaffoldReport, apply_scaffold, ensure_package_inits, is_safe_project_dir
from core.team_board import unmet_requirements
from core.verification_outcome import VerificationOutcome
from core.verifier import ProjectVerifier

logger = logging.getLogger(__name__)

# Befunde, die den Start/Import sicher brechen und von einem Entwickler behoben werden müssen.
_BLOCKING_ISSUE_TYPES = frozenset({
    "syntax_error", "unresolved_import_name", "malformed_ini_section",
    "conflicting_sqlalchemy_engines", "module_level_event_loop_call", "hidden_runtime_dependency",
})
_FALLBACK_OWNERS = ("backend", "database", "frontend", "api_integration")


def _is_contract_false_positive(mismatch, endpoints) -> bool:
    """Dynamische Pfade (`${BASE_URL}${url}`) und Router-Präfixe (`/api/items` ↔ Route `/items`)."""
    raw = (mismatch.frontend_call.raw_path or "").strip()
    if not raw.startswith("/"):
        return True
    first_segment = raw.split("/")[1] if len(raw) > 1 else ""
    if "${" in first_segment or first_segment.startswith("{"):
        return True
    if mismatch.mismatch_type != "MISSING_ENDPOINT":
        return False
    target = normalize_path(raw).strip("/").split("/")
    for endpoint in endpoints:
        route = endpoint.normalized_path.strip("/").split("/")
        if route and len(route) < len(target) and all(
            r == t or r == ":param" or t == ":param" for r, t in zip(route, target[-len(route):], strict=False)
        ):
            return True
    return False


class IntegrationMixin:
    """Gerüst vor und Integrations-Checkpoint nach der Entwicklungsphase."""

    def _trace_event(self, event: str, **fields) -> None:
        run_logger = getattr(self, "_run_logger", None)
        if run_logger is None:
            return
        try:
            run_logger.log_event(event, **fields)
        except Exception as e:  # noqa: BLE001 - Protokoll darf den Lauf nie gefährden
            logger.warning("Trace-Ereignis %s konnte nicht geschrieben werden: %r", event, e)

    def _apply_project_scaffold(
        self, project_dir: str, user_request: str, notify: Callable[[str], None],
    ) -> ScaffoldReport:
        report = apply_scaffold(project_dir, user_request)
        if report.created:
            shown = ", ".join(f"`{p}`" for p in report.created[:8])
            more = f" (+{len(report.created) - 8})" if len(report.created) > 8 else ""
            notify(f"  🧱 [cyan]Projektgerüst ({report.stack}):[/cyan] {shown}{more}")
            log_decision(project_dir, "project_scaffold_applied", f"Stack {report.stack}: {', '.join(report.created)}")
        if report.error:
            notify(f"  ⚠️ [dim yellow]Projektgerüst unvollständig: {report.error}[/dim yellow]")
        self._trace_event("project_scaffold", stack=report.stack, created=report.created, error=report.error)
        return report

    async def _run_integration_checkpoint(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
    ) -> list[str]:
        """Führt den Checkpoint aus und gibt Protokollzeilen zurück (für den Abschlussbericht)."""
        lines: list[str] = []
        if not is_safe_project_dir(project_dir):
            return lines
        lines.extend(await self._check_team_board_requirements(project_dir, notify))
        lines.extend(await self._run_frontend_backend_contract_review(project_dir, all_results, file_owners, notify, run_start_tokens))
        try:
            report = await asyncio.to_thread(run_pre_flight_check, project_dir)
        except Exception as e:  # noqa: BLE001 - Checkpoint ist Frühwarnung, kein Blocker
            notify(f"  ⚠️ [dim]Integrations-Checkpoint übersprungen: {e}[/dim]")
            return lines
        if report.error:
            return lines

        # 1) Deterministische Autofixes ohne LLM
        created_inits = await asyncio.to_thread(ensure_package_inits, project_dir)
        added: list[str] = []
        for issue in report.issues:
            if issue.issue_type not in ("missing_dependency", "hidden_runtime_dependency"):
                continue
            package = package_from_finding(issue.suggestion)
            target = manifest_for_package(Path(project_dir), package, issue.file) if package else None
            if not package or target is None:
                continue
            try:
                if add_requirement(target, package):
                    added.append(f"{package} ({target.name})")
            except (ValueError, OSError):
                continue
        if created_inits or added:
            detail = ", ".join([*created_inits[:5], *added[:8]])
            notify(f"  🔧 [green]Integrations-Checkpoint – deterministisch behoben:[/green] {detail}")
            lines.append(f"- 🔧 Integrations-Checkpoint: {len(created_inits)} `__init__.py` angelegt, {len(added)} Paket(e) ergänzt.")
            report = await asyncio.to_thread(run_pre_flight_check, project_dir)

        blocking = [i for i in report.issues if i.issue_type in _BLOCKING_ISSUE_TYPES]
        if not blocking:
            notify("  ✅ [green]Integrations-Checkpoint nach der Entwicklung bestanden.[/green]")
            lines.append("- ✅ Integrations-Checkpoint nach der Entwicklungsphase bestanden.")
            self._trace_event("integration_checkpoint", passed=True, auto_fixed=len(created_inits) + len(added))
            return lines

        if run_start_tokens is not None and (
            self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
        ):
            lines.append(f"- ⚠️ Integrations-Checkpoint: {len(blocking)} Befund(e), Fix-Runde wegen Budget übersprungen.")
            self._trace_event("integration_checkpoint", passed=False, issues=len(blocking), fixed=False, reason="budget")
            return lines

        # 2) Genau eine gezielte Fix-Runde je Datei-Owner
        by_owner: dict[str, list] = {}
        for issue in blocking:
            owner = file_owners.get(issue.file)
            if not owner or owner not in self._agents:
                owner = next((a for a in _FALLBACK_OWNERS if a in self._agents), None)
            if owner:
                by_owner.setdefault(owner, []).append(issue)
        fix_tasks = [
            AgentTask(
                task_id=f"integration_checkpoint_fix_{owner}",
                agent_id=owner,
                description=(
                    "Integrations-Checkpoint direkt nach der Entwicklungsphase: der Code lässt sich so "
                    "nicht starten/importieren. Behebe AUSSCHLIESSLICH diese Befunde, BEVOR QA und Review "
                    "beginnen - keine neuen Features:\n\n"
                    + "\n".join(
                        f"- [{i.issue_type}] {i.file}:{i.line} – {i.message}" + (f" Lösung: {i.suggestion}" if i.suggestion else "")
                        for i in issues
                    )
                ),
                project_dir=project_dir,
            )
            for owner, issues in by_owner.items()
        ]
        if not fix_tasks:
            lines.append(f"- ⚠️ Integrations-Checkpoint: {len(blocking)} Befund(e) ohne zuständigen Entwickler.")
            return lines

        notify(f"  🛠️ [bold yellow]Integrations-Checkpoint:[/bold yellow] {len(blocking)} Befund(e) → {', '.join(by_owner)}")
        fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)

        after = await asyncio.to_thread(run_pre_flight_check, project_dir)
        remaining = [i for i in after.issues if i.issue_type in _BLOCKING_ISSUE_TYPES]
        status = "behoben" if not remaining else f"{len(remaining)} Befund(e) offen"
        lines.append(f"- 🛠️ Integrations-Checkpoint: {len(blocking)} Befund(e) an {', '.join(by_owner)} → {status}.")
        log_decision(project_dir, "integration_checkpoint", f"{len(blocking)} Befund(e) → {status}")
        self._trace_event("integration_checkpoint", passed=not remaining, issues=len(blocking), remaining=len(remaining))
        return lines

    async def _run_frontend_backend_contract_review(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
    ) -> list[str]:
        """Review-Paar Frontend ↔ Backend: API-Aufrufe der UI gegen die echten Backend-Routen.

        Analyse 2026-09-15: `core/contract_verifier.py` existierte, wurde in keinem Lauf aufgerufen.
        Im nexus_resilience_gateway-Dashboard rief die UI `GET /metrics` ab, das Backend bot nur
        `/health` an - aufgefallen ist das niemandem. Genau eine gezielte Fix-Runde an `backend`
        (darf Routen UND UI-Aufrufe anpassen); dynamische Pfade und Router-Präfixe erzeugen keine Funde.
        """
        if not ENABLE_CONTRACT_REVIEW or "backend" not in self._agents:
            return []
        try:
            report = await asyncio.to_thread(verify_api_contracts, project_dir)
        except Exception as e:  # noqa: BLE001 - Review-Paar ist Frühwarnung, kein Blocker
            logger.warning("API-Contract-Review fehlgeschlagen: %r", e)
            return []
        mismatches = [m for m in report.mismatches if not _is_contract_false_positive(m, report.endpoints)]
        self._trace_event("contract_review", endpoints=report.endpoints_found, calls=report.frontend_calls_found, mismatches=len(mismatches))
        if not mismatches:
            return []
        described = [
            f"- [{m.mismatch_type}] {m.frontend_call.method} {m.frontend_call.raw_path} in {m.frontend_call.source_file}: "
            f"{m.details}" + (f" Hinweis: {m.suggested_fix}" if m.suggested_fix else "")
            for m in mismatches[:15]
        ]
        notify(f"  🤝 [bold yellow]Frontend↔Backend-Review:[/bold yellow] {len(mismatches)} API-Abweichung(en)")
        if run_start_tokens is not None and (
            self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
        ):
            return [f"- 🤝 ⚠️ Frontend↔Backend-Review: {len(mismatches)} Abweichung(en), Fix-Runde wegen Budget übersprungen."]
        task = AgentTask(
            task_id="contract_review_fix_backend",
            agent_id="backend",
            description=(
                "Review-Paar Frontend ↔ Backend: Die Oberfläche ruft API-Pfade auf, die das Backend so nicht anbietet. "
                "Gleiche beide Seiten an: Gehört der Endpunkt zum Auftrag, implementiere ihn im Backend; ist es ein "
                "falscher Pfad/eine falsche Methode im Frontend, korrigiere den Aufruf. Keine neuen Features darüber hinaus. "
                "Kläre Unklarheiten per ask_teammate mit `frontend`.\n\n" + "\n".join(described)
            ),
            project_dir=project_dir,
        )
        results = await self._run_agents_parallel([task], notify=notify)
        self._update_file_owners(file_owners, results)
        all_results.extend(results)
        after = await asyncio.to_thread(verify_api_contracts, project_dir)
        remaining = [m for m in after.mismatches if not _is_contract_false_positive(m, after.endpoints)]
        status = "behoben" if not remaining else f"{len(remaining)} offen"
        log_decision(project_dir, "contract_review", f"{len(mismatches)} Abweichung(en) → {status}")
        return [f"- 🤝 Frontend↔Backend-Review: {len(mismatches)} API-Abweichung(en) an backend → {status}."]

    async def _check_team_board_requirements(self, project_dir: str, notify: Callable[[str], None]) -> list[str]:
        """Gleicht die `requires`-Angaben der Übergaben mit dem echten Projektstand ab (core/team_board.py).

        Ein unerfüllter Bedarf ("frontend braucht `GET /api/metrics`") ist genau das Missverständnis
        zwischen Kollegen, das sonst erst im Browser-Check oder gar nicht auffällt.
        """
        if not ENABLE_TEAM_BOARD:
            return []
        try:
            unmet = await asyncio.to_thread(unmet_requirements, project_dir)
        except Exception as e:  # noqa: BLE001 - Abgleich ist Frühwarnung, kein Blocker
            logger.warning("Team-Board-Abgleich fehlgeschlagen: %r", e)
            return []
        self._trace_event("team_board_requirements", unmet=len(unmet))
        if not unmet:
            return []
        shown = "; ".join(f"{agent}: {req}" for agent, req in unmet[:6])
        notify(f"  🤝 [bold yellow]Team-Board – unerfüllter Bedarf:[/bold yellow] {shown}")
        return [f"- 🤝 Team-Board: {len(unmet)} unerfüllte Anforderung(en) zwischen Kollegen – {shown}"]

    async def _run_review_after_verification(
        self,
        *,
        user_request: str,
        task_summary: str,
        review_tasks: list[AgentTask],
        project_dir: str,
        results: list[AgentResult],
        file_owners: dict[str, str],
        verification_ok: bool,
        verification_summary: str,
        run_start_tokens: int | None,
        notify: Callable[[str], None],
        cancel_requested: Callable[[], bool] | None,
    ) -> tuple[list[AgentResult], bool, str, str, bool, bool]:
        """Review & Governance NACH der echten Verifikation (wie ein PR-Review nach grüner CI).

        1. Review-/Governance-Agenten bekommen den echten Verifikationsstatus als Kontext.
        2. Die Governance-Fix-Schleife behebt kritische Befunde.
        3. Haben Review/Fixes Dateien verändert, bestätigt ein Regressionstest (0 LLM-Tokens),
           dass die Testsuite weiterhin grün ist - sonst gilt der Lauf als nicht verifiziert.

        Gibt (results, verification_ok, verification_summary, governance_fix_summary,
        budget_aborted, manually_cancelled) zurück.
        """
        budget_aborted = False
        manually_cancelled = False
        governance_fix_summary = ""
        results_before = len(results)

        if review_tasks:
            status_note = (
                "## 🧪 Verifikationsstatus (echte Tests/Build VOR diesem Review)\n"
                + ("Die Verifikation ist GRÜN." if verification_ok else "Die Verifikation ist ROT - Details:")
                + "\n" + verification_summary[:1500]
            )
            for task in review_tasks:
                task.context += f"\n\n{status_note}"
            notify("🔍 [bold cyan]Review & Governance[/bold cyan] nach der echten Verifikation...")
            review_results, review_owners, budget_aborted, manually_cancelled = await self._run_department_hierarchy(
                user_request=user_request,
                task_summary=task_summary,
                agent_tasks=review_tasks,
                project_dir=project_dir,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
                enable_phase_checkpoint=False,
            )
            results.extend(review_results)
            file_owners.update(review_owners)

        if not (budget_aborted or manually_cancelled):
            results, governance_fix_summary, budget_aborted, manually_cancelled = await self._run_governance_fix_loop(
                project_dir=project_dir,
                all_results=results,
                file_owners=file_owners,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
            )

        changed_files = sorted({f for r in results[results_before:] for f in (r.files_written or [])})
        outcome = getattr(self, "last_verification_outcome", None)
        tests_ran_before = isinstance(outcome, VerificationOutcome) and outcome.ran("tests")
        if changed_files and tests_ran_before and not manually_cancelled:
            verifier = ProjectVerifier(project_dir)
            regression_lines: list[str] = []
            await self._resync_environment_if_dependencies_changed(
                verifier, results[results_before:], notify, regression_lines,
            )
            notify(f"  🔁 [yellow]Regressionstest nach Review-Änderungen[/yellow] ({len(changed_files)} Datei(en))...")
            report = await self._run_tests_logged(verifier, "regression_nach_review")
            if report.ran and report.passed:
                regression_lines.append(f"- 🔁 Regressionstest nach Review-Änderungen ({len(changed_files)} Datei(en)): grün.")
                if outcome.failed_checks == ["tests"]:
                    outcome.record("tests", True, "nach Review-Fixes grün")
            else:
                regression_lines.append(
                    f"- 🔁 ❌ Regressionstest nach Review-Änderungen fehlgeschlagen ({len(report.failures)} Testfehler) - "
                    f"geänderte Dateien: {', '.join(changed_files[:8])}"
                )
                outcome.record("tests", False, "Regression durch Review-Änderungen")
                if verification_ok:
                    notify("  ❌ [bold red]Review-Änderungen haben die Testsuite gebrochen[/bold red] – Lauf gilt als nicht verifiziert.")
                verification_ok = False
            verification_summary = verification_summary.rstrip() + "\n" + "\n".join(regression_lines)
        return results, verification_ok, verification_summary, governance_fix_summary, budget_aborted, manually_cancelled
