"""
agents/orchestrator/dispatch.py – DispatchMixin: Ausführungs-Helfer zum Dispatch einzelner
oder mehrerer Agenten-Tasks (Routing auf den passenden Agenten/Department-Lead per
task.agent_id, parallele Ausführung per asyncio.gather).
"""

import asyncio
import logging
from collections.abc import Callable

from config import (
    MAX_CONCURRENT_AGENTS,
    PROVIDER_EXHAUSTION_ABORT_RATIO,
    PROVIDER_EXHAUSTION_RUN_ABORT_RATIO,
    PROVIDER_EXHAUSTION_RUN_MIN_SAMPLE,
)
from core.message_bus import AgentResult, AgentTask
from core.provider_exhaustion import (
    all_failed_on_provider_exhaustion,
    infrastructure_failure_ratio,
    should_trip_breaker,
    should_trip_run_breaker,
)


class DispatchMixin:
    """Routet AgentTasks an den zuständigen Agenten und führt sie einzeln/parallel aus."""

    @property
    def _infra_results_this_run(self) -> list:
        """Alle Agenten-Ergebnisse seit Laufbeginn - Grundlage der laufweiten Breaker-Quote.
        Als Property mit Lazy-Initialisierung, damit der Mixin auch in Tests ohne vollständiges
        Orchestrator-Setup (agents/orchestrator/__init__.py) nutzbar bleibt."""
        if getattr(self, "_infra_results_store", None) is None:
            self._infra_results_store: list = []
        return self._infra_results_store

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
        should_stop: Callable[[], str | None] | None = None,
    ) -> list[AgentResult]:
        """
        Führt eine Welle von Agenten-Aufgaben aus, gedrosselt durch MAX_CONCURRENT_AGENTS.

        `should_stop` wird direkt VOR dem Start jeder einzelnen Aufgabe ausgewertet (nicht nur
        einmal zu Wellenbeginn) und liefert einen Grundtext, wenn nicht mehr gestartet werden
        soll - sonst None. Laufanalyse 2026-09-16: Das Budget wurde bisher nur am Phasenkopf und
        nach jedem SEQUENZIELLEN Mitglied geprüft. Bei MAX_CONCURRENT_AGENTS=2 arbeitet eine
        parallele Phase mit sechs Mitgliedern aber drei Blöcke nacheinander ab - dazwischen lag
        keine einzige Prüfung, obwohl genau dort Tokens im sechsstelligen Bereich anfallen (im
        Lauf `cloudpulse` allein 273.468 für den backend-Agenten). Ein Abbruch mitten in einem
        laufenden `asyncio.gather` ist weiterhin nicht sinnvoll möglich - eine noch gar nicht
        gestartete Aufgabe zu überspringen dagegen schon.
        """
        # Thundering-Herd-Schutz (siehe config.MAX_CONCURRENT_AGENTS-Docstring): begrenzt, wie
        # viele Agenten-Aufrufe INNERHALB dieser Welle wirklich gleichzeitig laufen, statt alle
        # Mitglieder eines Fachbereichs auf einmal gegen dieselben TPM-/RPM-Provider-Limits
        # laufen zu lassen. Ein neues Semaphore pro Aufruf ist bewusst so gewählt - es gibt
        # keine geteilte Zählung ÜBER mehrere `_run_agents_parallel()`-Wellen hinweg, da diese
        # im Orchestrator ohnehin sequenziell (nicht parallel zueinander) laufen.
        semaphore = asyncio.Semaphore(max(1, MAX_CONCURRENT_AGENTS))

        skipped: list[str] = []

        async def _wrapped(task: AgentTask) -> AgentResult | None:
            async with semaphore:
                grund = should_stop() if should_stop is not None else None
                if grund:
                    # Bewusst KEIN AgentResult: ein nie gestarteter Aufruf ist weder ein Erfolg
                    # noch ein Fehlschlag. Als Fehlschlag gezählt würde er die Erfolgsquoten in
                    # memory/run_history.py und die Infrastruktur-Quote des Circuit Breakers
                    # verfälschen; als Erfolg gezählt würde er Arbeit vortäuschen.
                    skipped.append(self._agents[task.agent_id].name if task.agent_id in self._agents else task.agent_id)
                    return None
                res = await self._run_single_agent(task)
            if notify:
                notify(self._status_notify_line("✅ [green]Abgeschlossen[/green]", "❌ [red]Fehler[/red]", res.agent_name, res.duration_seconds, res.success, res.error))
            return res

        results = await asyncio.gather(
            *[_wrapped(task) for task in agent_tasks],
            return_exceptions=False,
        )
        results = [r for r in results if r is not None]
        if skipped and notify:
            grund = (should_stop() if should_stop is not None else None) or "Budget erschöpft"
            notify(
                f"  ⏭️ [yellow]{grund} – {len(skipped)} noch nicht gestartete(r) Agenten-Aufruf(e) "
                f"dieser Welle übersprungen: {', '.join(skipped)}.[/yellow]"
            )

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

        # Dritte Sicht neben Welle (oben) und Folge-Fehlschlägen (department.py): die Quote über
        # den GESAMTEN Lauf. Nur so fällt ein Engpass auf, der sich gleichmäßig und von Erfolgen
        # durchsetzt über viele kleine Wellen verteilt - siehe should_trip_run_breaker() für den
        # Lauf, an dem das auffiel.
        self._infra_results_this_run.extend(results)
        if not getattr(self, "_provider_breaker_tripped", False) and should_trip_run_breaker(
            self._infra_results_this_run,
            PROVIDER_EXHAUSTION_RUN_ABORT_RATIO,
            PROVIDER_EXHAUSTION_RUN_MIN_SAMPLE,
        ):
            self._provider_exhausted_this_run = True
            self._provider_breaker_tripped = True
            anteil = infrastructure_failure_ratio(self._infra_results_this_run)
            if notify:
                notify(
                    f"🛑 [red]Seit Laufbeginn scheiterten {anteil:.0%} aller Agenten-Aufrufe "
                    f"({len(self._infra_results_this_run)} insgesamt) an fehlenden API-Kontingenten/"
                    "Schlüsseln - keine einzelne Welle fiel dabei auf. Der Lauf wird sauber "
                    "beendet, statt weiter Tokens zu verbrauchen.[/red]"
                )
        return results
