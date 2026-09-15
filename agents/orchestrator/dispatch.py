"""
agents/orchestrator/dispatch.py – DispatchMixin: Ausführungs-Helfer zum Dispatch einzelner
oder mehrerer Agenten-Tasks (Routing auf den passenden Agenten/Department-Lead per
task.agent_id, parallele Ausführung per asyncio.gather).
"""

import asyncio
import logging
from collections.abc import Callable

from config import MAX_CONCURRENT_AGENTS, PROVIDER_EXHAUSTION_ABORT_RATIO
from core.message_bus import AgentResult, AgentTask
from core.provider_exhaustion import (
    all_failed_on_provider_exhaustion,
    infrastructure_failure_ratio,
    should_trip_breaker,
)


class DispatchMixin:
    """Routet AgentTasks an den zuständigen Agenten und führt sie einzeln/parallel aus."""

    def _provider_exhaustion_ticket_note(self) -> str:
        """Kurzer Hinweistext für ein Backlog-Ticket, das während eines Laufs eröffnet wurde,
        in dem mindestens eine Welle vollständig an einer API-Kontingent-Erschöpfung
        scheiterte (siehe _run_agents_parallel() oben) - macht den Unterschied zwischen einem
        echten, ungeprüften Befund und einem bloßen Kontingent-Engpass für eine spätere
        menschliche/automatische Prüfung sofort sichtbar. Leer, wenn keine Erschöpfung
        aufgetreten ist (kein unnötiger Zusatztext im Normalfall)."""
        if not getattr(self, "_provider_exhausted_this_run", False):
            return ""
        return (
            "\n\n⚠️ Hinweis: Während dieses Laufs scheiterte mindestens eine Welle von "
            "Agenten-Aufrufen vollständig an einer API-Kontingent-Erschöpfung (429/"
            "RESOURCE_EXHAUSTED) - nicht notwendigerweise an einem echten Code-Defekt. Ein "
            "erneuter automatischer Versuch (core/backlog_worker.py._governance_retry_pool()) "
            "mit wieder verfügbarem Kontingent kann ausreichen, statt dass hier zwingend "
            "menschlich eingegriffen werden muss."
        )

    async def _run_single_agent(self, task: AgentTask) -> AgentResult:
        agent = self._agents.get(task.agent_id) or self._dept_leads.get(task.agent_id)
        if not agent:
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.agent_id,
                agent_name=task.agent_id,
                success=False,
                content="",
                error=f"Unbekannter Agent: '{task.agent_id}'",
            )
        return await self._execute_and_log(agent, task)

    async def _execute_and_log(self, agent, task: AgentTask) -> AgentResult:
        """Führt einen Agenten-Aufruf aus und protokolliert ihn im Lauf-Log.

        Zentraler Engpass ALLER Agenten-Aufrufe - auch Delegation/Konsolidierung der
        Fachbereichsleiter, Retrospektive und Trainer. Analyse 2026-09-15: diese riefen
        `execute()` direkt auf, im nexus_resilience_gateway-Trace fehlten dadurch 9 von 27
        Aufrufen (~100k Tokens ohne Evidenz). Protokollierung darf einen Lauf nie gefährden.
        """
        result = await agent.execute(task)
        try:
            self._note_agent_call(agent, result)
            run_logger = getattr(self, "_run_logger", None)
            if run_logger is not None:
                run_logger.log_agent_result(
                    result, requested_model=getattr(getattr(agent, "_llm", None), "model_name", ""),
                )
        except Exception as e:
            # Eine Telemetrie-Lücke muss sichtbar sein, sonst fehlen Aufrufe lautlos in jeder Auswertung.
            logging.getLogger(__name__).warning(
                "Agenten-Aufruf '%s' konnte nicht ins Lauf-Log geschrieben werden: %r", task.agent_id, e,
            )
        return result

    async def _run_agents_parallel(
        self,
        agent_tasks: list[AgentTask],
        notify: Callable[[str], None] | None = None,
    ) -> list[AgentResult]:
        # Thundering-Herd-Schutz (siehe config.MAX_CONCURRENT_AGENTS-Docstring): begrenzt, wie
        # viele Agenten-Aufrufe INNERHALB dieser Welle wirklich gleichzeitig laufen, statt alle
        # Mitglieder eines Fachbereichs auf einmal gegen dieselben TPM-/RPM-Provider-Limits
        # laufen zu lassen. Ein neues Semaphore pro Aufruf ist bewusst so gewählt - es gibt
        # keine geteilte Zählung ÜBER mehrere `_run_agents_parallel()`-Wellen hinweg, da diese
        # im Orchestrator ohnehin sequenziell (nicht parallel zueinander) laufen.
        semaphore = asyncio.Semaphore(max(1, MAX_CONCURRENT_AGENTS))

        async def _wrapped(task: AgentTask) -> AgentResult:
            async with semaphore:
                res = await self._run_single_agent(task)
            if notify:
                notify(self._status_notify_line("✅ [green]Abgeschlossen[/green]", "❌ [red]Fehler[/red]", res.agent_name, res.duration_seconds, res.success, res.error))
            return res

        results = await asyncio.gather(
            *[_wrapped(task) for task in agent_tasks],
            return_exceptions=False,
        )
        results = list(results)

        # Team-Optimierung (KI-Team-Weiterentwicklung, echter Fund: memory/history_default.json,
        # 2026-09-09 - 11 von 32 Agenten-Aufrufen scheiterten am Ende eines Laufs in Folge mit
        # `total_tokens: 0`, weil alle konfigurierten Provider gleichzeitig ihr Tages-Kontingent
        # ausgeschöpft hatten). Bisher war das im Ergebnis von keinem echten Code-Defekt zu
        # unterscheiden - ein danach eröffnetes "unresolved-governance-critical-"-Ticket
        # (agents/orchestrator/verification.py) sah identisch aus, egal ob die Ursache ein
        # echter Bug oder schlicht ein leeres Tages-Kontingent war. self._provider_exhausted_
        # this_run markiert das für den REST des Laufs (bleibt einmal gesetzt True, eine spätere
        # erfolgreiche Welle nach Kontingent-Reset überschreibt es bewusst NICHT zurück auf
        # False) - agents/orchestrator/verification.py nutzt das, um betroffene Tickets ehrlich
        # zu kennzeichnen statt sie wie einen ungeprüften echten Befund wirken zu lassen.
        if all_failed_on_provider_exhaustion(results):
            self._provider_exhausted_this_run = True
            if notify:
                notify(
                    "⚠️ [yellow]Alle Agenten dieser Welle scheiterten an einer API-Kontingent-"
                    "Erschöpfung (429/RESOURCE_EXHAUSTED) - nicht an einem echten Befund.[/yellow]"
                )

        # Circuit Breaker (realer Fund workspace/event_ticket_api: 19 von 21 Aufrufen an
        # erschöpften Kontingenten gescheitert, 0 geschriebene Dateien - der Lauf arbeitete
        # trotzdem alle Phasen ab, startete die Verifikation und schrieb einen irreführenden
        # Projektstatus). all_failed_on_provider_exhaustion() oben greift nur bei einer
        # VOLLSTÄNDIG gescheiterten Welle; real ist das Bild fast immer gemischt, weil einzelne
        # Aufrufe noch aus einem Restkontingent bedient werden. Deshalb zusätzlich eine Quote.
        if should_trip_breaker(results, PROVIDER_EXHAUSTION_ABORT_RATIO):
            self._provider_exhausted_this_run = True
            self._provider_breaker_tripped = True
            anteil = infrastructure_failure_ratio(results)
            if notify:
                notify(
                    f"🛑 [red]{anteil:.0%} der Agenten dieser Welle scheiterten an fehlenden API-"
                    "Kontingenten/Schlüsseln. Der Lauf wird sauber beendet, statt weiter Tokens "
                    "für einen Lauf zu verbrauchen, der nichts produzieren kann.[/red]"
                )
        return results
