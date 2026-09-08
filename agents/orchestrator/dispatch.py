"""
agents/orchestrator/dispatch.py – DispatchMixin: Ausführungs-Helfer zum Dispatch einzelner
oder mehrerer Agenten-Tasks (Routing auf den passenden Agenten/Department-Lead per
task.agent_id, parallele Ausführung per asyncio.gather).
"""

import asyncio
from collections.abc import Callable

from core.message_bus import AgentResult, AgentTask


class DispatchMixin:
    """Routet AgentTasks an den zuständigen Agenten und führt sie einzeln/parallel aus."""

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
        return await agent.execute(task)

    async def _run_agents_parallel(
        self,
        agent_tasks: list[AgentTask],
        notify: Callable[[str], None] | None = None,
    ) -> list[AgentResult]:
        """
        Führt mehrere AgentTasks per asyncio.gather() gleichzeitig aus (z.B. frontend/backend/
        devops innerhalb einer Fachbereichs-Phase, siehe agents/orchestrator/department.py).

        agent.execute() (agents/base_agent.py) fängt bereits jede Exception aus dem eigentlichen
        Agenten-Lauf selbst ab und liefert dafür ein AgentResult(success=False, error=...) - in
        der Praxis "kann" hier also nichts mehr raisen. Team-Optimierung (Robustheits-Härtung):
        return_exceptions=True + Nachbehandlung ist trotzdem die korrekte Absicherung, statt sich
        darauf zu verlassen, dass IMMER jeder Codepfad in execute()/notify() jede Exception
        selbst fängt - eine einzelne, aus welchem Grund auch immer doch durchschlagende Exception
        (z.B. ein Bug in notify() selbst, das außerhalb von execute() läuft) hätte sonst per
        asyncio.gather(..., return_exceptions=False) den GESAMTEN Aufruf abgebrochen und dabei
        auch die bereits fertigen Ergebnisse der anderen, unabhängig laufenden Branches verworfen
        - ein einzelner kaputter Zweig (z.B. devops) hätte damit auch fertige Ergebnisse von
        frontend/backend mitgerissen, obwohl diese komplett unabhängig voneinander liefen.
        """
        async def _wrapped(task: AgentTask) -> AgentResult:
            res = await self._run_single_agent(task)
            if notify:
                notify(self._status_notify_line("✅ [green]Abgeschlossen[/green]", "❌ [red]Fehler[/red]", res.agent_name, res.duration_seconds, res.success, res.error))
            return res

        raw_results = await asyncio.gather(
            *[_wrapped(task) for task in agent_tasks],
            return_exceptions=True,
        )
        results: list[AgentResult] = []
        for task, res in zip(agent_tasks, raw_results, strict=True):
            if isinstance(res, BaseException):
                if notify:
                    notify(f"  ❌ [bold red]{task.agent_id} ist unerwartet fehlgeschlagen:[/bold red] {res}")
                results.append(AgentResult(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    agent_name=task.agent_id,
                    success=False,
                    content="",
                    error=str(res),
                ))
            else:
                results.append(res)
        return results
