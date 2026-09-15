"""
agents/orchestrator/efficiency.py – EfficiencyMixin: Token-Effizienz und Modell-Abwertungen pro Lauf

Analyse 2026-09-15:
- ~95 % Prompt-Tokens, die Cache-Quote war nirgends sichtbar.
- Im nexus_resilience_gateway-Lauf wurde JEDE `gemini-pro-latest`-Anfrage still von
  `gemini-3.8-flash` beantwortet (`model_downgraded`) – der Nutzer erfuhr davon nichts, obwohl
  genau diese Rollen (backend, security) scheiterten.

Der Mixin sammelt pro Lauf Abwertungen, Cache-Treffer und eingesparten Kontext und liefert einen
kurzen, deterministischen Abschnitt für den Abschlussbericht sowie Felder für `run_closed`.
"""

from __future__ import annotations

import logging

from core.message_bus import AgentResult
from core.token_guard import token_guard

logger = logging.getLogger(__name__)


def _usage_totals() -> tuple[int, int]:
    """(Prompt-Tokens, Cache-Lese-Tokens) über alle Modelle seit Prozessstart."""
    prompt = cache = 0
    for stat in getattr(token_guard, "_stats", {}).values():
        prompt += getattr(stat, "prompt_tokens", 0) or 0
        cache += getattr(stat, "cache_read_tokens", 0) or 0
    return prompt, cache


class EfficiencyMixin:
    """Token-Effizienz-Kennzahlen und sichtbare Modell-Abwertungen."""

    def _begin_efficiency_tracking(self) -> None:
        self._efficiency_baseline = _usage_totals()
        self._model_downgrades: list[dict] = []

    def _note_agent_call(self, agent, result: AgentResult) -> None:
        requested = getattr(getattr(agent, "_llm", None), "model_name", "") or ""
        effective = result.model_used or ""
        if not requested or not effective or effective == "deterministisch":
            return
        try:
            from core.llm_factory import is_same_model
            downgraded = not is_same_model(requested, effective)
        except Exception as e:  # noqa: BLE001 - Kennzahl darf den Lauf nie gefährden
            logger.warning("Modellvergleich fehlgeschlagen: %r", e)
            return
        if downgraded:
            if not hasattr(self, "_model_downgrades"):
                self._model_downgrades = []
            self._model_downgrades.append({"agent_id": result.agent_id, "requested": requested, "effective": effective})

    def _efficiency_snapshot(self, results: list[AgentResult]) -> dict:
        base_prompt, base_cache = getattr(self, "_efficiency_baseline", (0, 0))
        prompt, cache = _usage_totals()
        run_prompt = max(prompt - base_prompt, 0)
        run_cache = max(cache - base_cache, 0)
        downgrades = list(getattr(self, "_model_downgrades", []))
        return {
            "prompt_tokens": run_prompt,
            "cache_read_tokens": run_cache,
            "cache_hit_ratio": round(run_cache / run_prompt, 3) if run_prompt else 0.0,
            "context_chars_compacted": sum(getattr(r, "context_chars_compacted", 0) or 0 for r in results),
            "model_downgrades": len(downgrades),
            "watchdog_interventions": sum(len(getattr(r, "watchdog_events", []) or []) for r in results),
            "downgraded_agents": sorted({d["agent_id"] for d in downgrades}),
        }

    def _build_efficiency_section(self, results: list[AgentResult]) -> str:
        snapshot = self._efficiency_snapshot(results)
        lines = ["### ⚡ Token-Effizienz dieses Laufs"]
        if snapshot["prompt_tokens"]:
            lines.append(
                f"- Cache-Treffer: {snapshot['cache_hit_ratio']:.0%} der {snapshot['prompt_tokens']:,} Prompt-Tokens"
            )
        if snapshot["context_chars_compacted"]:
            lines.append(
                f"- Kontext-Verdichtung: ~{snapshot['context_chars_compacted'] // 4:,} Tokens je Folge-Iteration eingespart "
                f"({snapshot['context_chars_compacted']:,} Zeichen)"
            )
        watchdog = sorted({f"{r.agent_id}: {e}" for r in results for e in (getattr(r, "watchdog_events", []) or [])})
        if watchdog:
            lines.append(f"- 🛡️ Watchdog-Eingriffe: {', '.join(watchdog[:10])}")
        downgrades = getattr(self, "_model_downgrades", [])
        if downgrades:
            pairs = sorted({f"{d['agent_id']} ({d['requested']} → {d['effective']})" for d in downgrades})
            lines.append(
                f"- ⚠️ {len(downgrades)} Aufruf(e) liefen mit einem anderen Modell als konfiguriert "
                f"(Kontingent/Fallback): {', '.join(pairs[:8])}. Ergebnisse dieser Rollen kritisch prüfen."
            )
        return "\n".join(lines) if len(lines) > 1 else ""
