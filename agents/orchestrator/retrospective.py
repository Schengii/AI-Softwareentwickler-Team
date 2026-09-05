"""
agents/orchestrator/retrospective.py – RetrospectiveMixin: Retrospektive nach Laufende sowie
die Selbstoptimierungs-Schleife des Agent-Trainers (extrahiert & speichert Lern-Regeln
persistent, damit alle Agenten aus vergangenen Fehlern/Läufen lernen).
"""

import json
import re

from core.message_bus import AgentResult, AgentTask


class RetrospectiveMixin:
    """Erstellt Retrospektiven und speist die persistente Agenten-Wissensbasis."""

    async def _run_retrospective(
        self,
        user_request: str,
        results: list[AgentResult],
        total_duration: float,
    ) -> AgentResult | None:
        retro_agent = self._agents.get("retrospective")
        if not retro_agent:
            return None

        retro_context = f"NUTZERAUFGABE: {user_request}\n\nTEAM-ERGEBNISSE:\n"
        for r in results:
            status = "Erfolgreich" if r.success else f"Fehler: {r.error}"
            retro_context += f"- {r.agent_name} ({r.agent_id}): {status} | Dauer: {r.duration_seconds:.1f}s | Tokens: {r.total_tokens}\n"
            if r.content:
                retro_context += f"  Auszug: {r.content[:250]}...\n"

        task = AgentTask(
            task_id="retro_task",
            agent_id="retrospective",
            description="Erstelle eine ehrliche und konstruktive Retrospektive für dieses Projekt.",
            context=retro_context,
        )
        return await retro_agent.execute(task)

    async def _run_agent_trainer_self_optimization(
        self,
        user_request: str,
        results: list[AgentResult],
        retro_content: str,
        verification_ok: bool = True,
        verification_summary: str = "",
    ) -> AgentResult | None:
        trainer = self._agents.get("agent_trainer")
        if not trainer:
            return None

        has_errors = any(not r.success for r in results)
        high_usage = any(r.total_tokens > 4000 for r in results)

        # Team-Optimierung (Retrospektive 2026-09-05, Punkt 4): AgentResult.success beschreibt
        # nur, ob ein Agent seinen EIGENEN Tool-Aufruf ohne Absturz beendet hat - ein Agent, der
        # anstandslos, aber fachlich falschen Code liefert (genau die Fälle, die
        # recurring_failure_ticket_opened/unresolved_governance_critical_ticket_opened auslösen,
        # siehe agents/orchestrator/verification.py), zählt hier NICHT als Fehler. Real
        # beobachtet (workspace/zeiterfassung_app, 2026-09-04): drei Läufe mit identischem
        # DTZ001-/Testfehler, aber KEIN einziger davon hätte has_errors=True ausgelöst, weil
        # jeder beteiligte Agent seinen Tool-Aufruf technisch erfolgreich beendete - der
        # Selbstlern-Kanal (memory/agent_learnings.json) bekam dadurch nie die Chance, aus einem
        # der eigentlich lehrreichsten Signale (ein Fehler, den das Team trotz Eskalation NICHT
        # selbst beheben konnte) etwas zu lernen.
        if not has_errors and not high_usage and verification_ok:
            return None

        context = (
            f"PROJEKTAUFGABE: {user_request}\n\n"
            f"RETROSPEKTIVE & ERKENNTNISSE:\n{retro_content[:1500]}\n\n"
            f"FEHLERHAFTE ODER TOKEN-INTENSIVE AGENTEN:\n"
        )
        for r in results:
            if not r.success or r.total_tokens > 4000:
                context += f"- {r.agent_name} ({r.agent_id}): Success={r.success}, Tokens={r.total_tokens}, Error={r.error}\n"
        if not verification_ok and verification_summary.strip():
            context += (
                "\nECHTE VERIFIKATION SCHLUG FEHL (Tests/Governance/Lint blieben rot, obwohl "
                "kein Agent selbst einen Fehler meldete - das ist das eigentlich lehrreichste "
                f"Signal hier):\n{verification_summary.strip()[:2000]}\n"
            )

        task = AgentTask(
            task_id="trainer_auto_opt",
            agent_id="agent_trainer",
            description="Analysiere die aufgetretenen Fehler/Ineffizienzen und liefere konkrete Prompt-Schärfungen zur Selbstoptimierung der Agenten.",
            context=context,
        )
        trainer_result = await trainer.execute(task)

        if trainer_result and trainer_result.success and trainer_result.content:
            self._extract_and_store_learnings(trainer_result.content)

        return trainer_result

    def _extract_and_store_learnings(self, report_text: str) -> None:
        """
        Speichert die Lern-Regeln aus dem Trainer-Report persistent (memory/agent_learnings.json),
        damit ALLE Agenten aus vergangenen Fehlern/Läufen lernen (BaseAgent.execute() reichert
        jeden System-Prompt automatisch mit den gespeicherten Regeln des jeweiligen Agenten an).

        Primär über den maschinenlesbaren ```json-Block (robust, siehe AgentTrainerAgent),
        mit Fallback auf die alte text-musterbasierte Extraktion, falls das Modell den
        JSON-Block einmal nicht liefert. Jede agent_id wird gegen die echten Agenten/Leads
        validiert, damit keine erfundene oder falsch geschriebene Rolle in der Wissensbasis landet.
        """
        from memory.agent_knowledge_base import agent_knowledge_base

        valid_agent_ids = set(self._agents.keys()) | set(self._dept_leads.keys())
        learnings = self._parse_structured_learnings(report_text) or self._parse_legacy_text_learnings(report_text)

        for entry in learnings:
            agent_id = entry.get("agent_id", "")
            rule = (entry.get("rule") or "").strip()
            if agent_id in valid_agent_ids and len(rule) > 15:
                agent_knowledge_base.add_learning(agent_id, rule)

    @staticmethod
    def _parse_structured_learnings(report_text: str) -> list[dict]:
        """
        Sucht NICHT nur den ersten ```json-Block, sondern den ersten, der wirklich einen
        "learnings"-Schlüssel enthält. Realer Fund aus einem echten Lauf: Der Trainer-Bericht
        enthält in seinen Prompt-Diff-Beispielen (Abschnitt "Konkrete Prompt-Verbesserungen")
        selbst oft ein illustratives ```json-Snippet VOR dem eigentlichen Lern-Block am Ende –
        ein reines "ersten Treffer nehmen" ignoriert dann den echten Block komplett und lässt
        alle Lern-Regeln des Laufs stillschweigend verloren gehen (kein Fehler, kein Log).
        """
        for match in re.finditer(r"```json\s*\n(.*?)```", report_text, re.DOTALL):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            learnings = data.get("learnings") if isinstance(data, dict) else None
            if isinstance(learnings, list):
                return learnings
        return []

    @staticmethod
    def _parse_legacy_text_learnings(report_text: str) -> list[dict]:
        """Fallback, falls der Trainer (entgegen der Anweisung) keinen gültigen JSON-Block liefert."""
        learnings: list[dict] = []
        current_agent: str | None = None
        for line in report_text.splitlines():
            if "Betroffener Agent:" in line:
                # \**: toleriert Markdown-Fettschrift ("**Betroffener Agent:**"), die reale
                # Modell-Ausgaben durchgehend verwenden – ohne das schlug dieses Muster in
                # der Praxis nie an (bei einem echten Testlauf entdeckt).
                match = re.search(r'Betroffener Agent:\**\s*[`\'"]?([a-zA-Z0-9_]+)', line)
                if match:
                    current_agent = match.group(1).replace("_agent", "")
            elif current_agent and ("Vorgeschlagene Ergänzung" in line or line.strip().startswith('"') or line.strip().startswith("- ")):
                clean_rule = line.strip(' "-*#')
                if len(clean_rule) > 15:
                    learnings.append({"agent_id": current_agent, "rule": clean_rule})
        return learnings
