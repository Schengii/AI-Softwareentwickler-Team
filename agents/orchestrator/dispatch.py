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
        async def _wrapped(task: AgentTask) -> AgentResult:
            res = await self._run_single_agent(task)
            if notify:
                notify(self._status_notify_line("✅ [green]Abgeschlossen[/green]", "❌ [red]Fehler[/red]", res.agent_name, res.duration_seconds, res.success, res.error))
            return res

        results = await asyncio.gather(
            *[_wrapped(task) for task in agent_tasks],
            return_exceptions=False,
        )
        return list(results)
