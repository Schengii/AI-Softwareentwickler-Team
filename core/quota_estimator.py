"""
core/quota_estimator.py – Echtzeit Quota- & Token-Status aller Provider

Erfasst und berechnet:
- Live-Verbrauch pro Provider & Modell (Prompt, Completion, Total)
- Verbleibende Quota (Free Tier Limits & Reset-Zyklen)
- Cooldown- und Rate-Limit Status
"""

from typing import Any

from core.token_guard import token_guard

# Typische monatliche/tägliche Free-Tier Kontingente
FREE_TIER_LIMITS = {
    "gemini": {
        "name": "Google Gemini (Flash)",
        "limit_desc": "15 RPM / 1.000.000 Tokens/min (Kostenlos)",
        "approx_daily_budget": 1_000_000,
    },
    "claude": {
        "name": "Anthropic Claude",
        "limit_desc": "Kein dauerhaftes Gratis-Kontingent – kostenpflichtig, außer Groq-Fallback greift",
        "approx_daily_budget": 0,
    },
    "groq": {
        "name": "Groq Turbo (LLaMA/GPT-OSS)",
        "limit_desc": "30 RPM / 6.000 Tokens/min (Kostenlos, tägl. Reset)",
        "approx_daily_budget": 500_000,
    },
    "deepseek": {
        "name": "DeepSeek Reasoner/V3",
        "limit_desc": "Pay-as-you-go / Initiales Guthaben",
        "approx_daily_budget": 200_000,
    },
    "tavily": {
        "name": "Tavily Search API",
        "limit_desc": "1.000 Suchanfragen / Monat (Kostenlos)",
        "approx_daily_budget": 1_000,
    },
    "openrouter": {
        "name": "OpenRouter Universal",
        "limit_desc": "Kostenlose Modelle & Universal Fallback",
        "approx_daily_budget": 250_000,
    },
    "huggingface": {
        "name": "Hugging Face Inference",
        "limit_desc": "Kostenlose Community Rate Limits",
        "approx_daily_budget": 100_000,
    }
}


class QuotaEstimator:
    """Berechnet Verbrauchs- und Rest-Kontingent-Übersichten."""

    @staticmethod
    def get_agent_availability() -> list[dict[str, Any]]:
        """
        Realer Fund: `/tokens` zeigte bisher nur Verbrauch PRO MODELL, nie, welcher AGENT
        (`agents/*_agent.py`, je über `config.AGENT_MODELS` fest einem Modell zugeordnet)
        davon gerade betroffen ist - eine Nutzerin sah z.B. "claude-sonnet-5: 🚨 Cooldown",
        musste aber selbst wissen/nachschlagen, dass das u.a. `security`, `code_reviewer` und
        `architect` betrifft. Ordnet jeden konfigurierten Agenten seinem aktuellen Modell
        (inkl. Fachbereichs-/Env-Overrides, siehe `config.get_model_for_agent()`) und dessen
        Live-Verfügbarkeit zu.
        """
        from config import AGENT_MODELS, get_model_for_agent
        exhausted_by_model = {d["model_name"]: d for d in token_guard.get_exhausted_details()}

        rows = []
        for agent_id in sorted(AGENT_MODELS):
            model_name = get_model_for_agent(agent_id)
            exhaustion = exhausted_by_model.get(model_name)
            rows.append({
                "agent_id": agent_id,
                "model_name": model_name,
                "available": exhaustion is None,
                "available_at": exhaustion["available_at"] if exhaustion else None,
                "reason": exhaustion["reason"] if exhaustion else None,
            })
        return rows

    @staticmethod
    def _bucket_usage_by_provider(models: dict[str, dict[str, Any]]) -> dict[str, int]:
        """Ordnet eine {Modellname: Verbrauchsstatistik}-Zuordnung (egal ob aus
        core/token_guard.py.get_summary() für die aktuelle Sitzung oder aus
        memory/cost_history.py.get_today_totals() für den gesamten Kalendertag - beide haben
        dieselbe Form) nach Provider zusammen. Extrahiert aus dem vormals in
        get_detailed_report() inline stehenden Code, damit get_proactive_daily_budget_warnings()
        unten dieselbe Zuordnungslogik wiederverwenden kann, statt sie ein zweites Mal (und
        potenziell abweichend) zu implementieren."""
        provider_usage: dict[str, int] = {
            "gemini": 0,
            "claude": 0,
            "groq": 0,
            "deepseek": 0,
            "openrouter": 0,
            "huggingface": 0,
            "other": 0,
        }
        for model_name, stat in models.items():
            m_lower = model_name.lower()
            tokens = stat.get("total_tokens", 0)
            if "gemini" in m_lower:
                provider_usage["gemini"] += tokens
            elif "claude" in m_lower:
                provider_usage["claude"] += tokens
            elif "groq" in m_lower:
                provider_usage["groq"] += tokens
            elif "deepseek" in m_lower:
                provider_usage["deepseek"] += tokens
            elif "openrouter" in m_lower:
                provider_usage["openrouter"] += tokens
            elif "huggingface" in m_lower:
                provider_usage["huggingface"] += tokens
            else:
                provider_usage["other"] += tokens
        return provider_usage

    @staticmethod
    def get_detailed_report() -> dict[str, Any]:
        summary = token_guard.get_summary()
        models = summary.get("models", {})
        grand_total = summary.get("grand_total_tokens", 0)
        exhausted = summary.get("exhausted_models", [])

        return {
            "grand_total_tokens": grand_total,
            "models_detail": models,
            "provider_usage": QuotaEstimator._bucket_usage_by_provider(models),
            "exhausted_models": exhausted,
            "free_tier_limits": FREE_TIER_LIMITS,
        }

    @staticmethod
    def get_proactive_daily_budget_warnings(threshold: float = 0.8) -> list[str]:
        """Team-Optimierung (Retrospektive 2026-09-07): das bisherige Quota-Management war rein
        REAKTIV - core/token_guard.py markiert ein Modell erst als erschöpft, NACHDEM ein
        echter 429/Rate-Limit-Fehler eintraf (siehe core/llm_factory.py, jeder
        `mark_model_exhausted()`-Aufruf steht dort in einem `except`-Block). Das Team arbeitet
        dadurch faktisch "bis zum Anschlag", bevor überhaupt umgeschaltet wird - sichtbar an der
        Häufung von Fallback-Ketten-Commits (OpenRouter/DeepSeek als weitere Ausweichziele), die
        jeweils NACH einer bereits eingetretenen Erschöpfung nachgerüstet wurden.

        Gibt eine Warnung PRO Provider zurück, dessen Verbrauch bereits `threshold` (Standard
        80%) seines ungefähren Tages-Kontingents (FREE_TIER_LIMITS) erreicht hat - BEVOR der
        erste 429 überhaupt eintritt. Nutzt bewusst NICHT core/token_guard.py (reiner
        In-Memory-Zähler DIESES EINEN Prozesses, bei jedem Neustart wieder bei Null - siehe
        memory/cost_history.py-Moduldocstring), sondern den über memory/cost_history.py.
        get_today_totals() kumulierten Verbrauch des GANZEN Kalendertags (UTC) über ALLE
        Sitzungen hinweg: mehrere kurze CLI-Sitzungen am selben Tag (der real übliche
        Nutzungs-Rhythmus, nicht ein einziger durchgehender Dauerlauf) summieren sich hier
        korrekt, statt bei jedem Neustart wieder unsichtbar bei Null zu beginnen. Ein Aufrufer
        (agents/orchestrator/__init__.py vor Laufstart, analog zum bestehenden Projekt-
        Budget-Check dort) kann diese Warnung dem Team/der Nutzerin VOR weiterem Tokenverbrauch
        zeigen, statt erst auf den reaktiven Cooldown zu warten. Rein informativ (keine Rückgabe
        blockiert etwas) - Provider ohne definiertes Tages-Budget (`approx_daily_budget == 0`,
        z.B. Claude ohne Gratis-Kontingent) werden übersprungen, da "80% von 0" keine sinnvolle
        Warnschwelle ergibt."""
        from memory.cost_history import get_today_totals

        provider_usage = QuotaEstimator._bucket_usage_by_provider(get_today_totals())
        warnings = []
        for p_key, info in FREE_TIER_LIMITS.items():
            budget = info["approx_daily_budget"]
            if budget <= 0:
                continue
            used = provider_usage.get(p_key, 0)
            ratio = used / budget
            if ratio < threshold:
                continue
            warnings.append(
                f"⚠️ {info['name']}: heute bereits `{used:,}` von ca. `{budget:,}` Tokens des "
                f"Tages-Kontingents verbraucht ({ratio * 100:.0f}%, über alle Sitzungen hinweg) "
                f"- Erschöpfung (und automatischer Fallback) steht bevor."
            )
        return warnings

    @staticmethod
    def format_markdown_table() -> str:
        report = QuotaEstimator.get_detailed_report()
        grand_total = report["grand_total_tokens"]
        provider_usage = report["provider_usage"]
        exhausted = report["exhausted_models"]

        lines = [
            "## 🪙 Live Tokenverbrauch & Quota-Übersicht\n",
            f"**Gesamtverbrauch dieser Sitzung:** `{grand_total:,}` Tokens\n",
            "| Provider / KI-Dienst | Verbraucht (Tokens) | Status / Modell | Kostenloses Limit & Kontingent |",
            "|---|---|---|---|",
        ]

        for p_key, info in FREE_TIER_LIMITS.items():
            used = provider_usage.get(p_key, 0)
            budget = info["approx_daily_budget"]
            remaining = max(budget - used, 0)
            
            # Prüfe ob ein Modell dieses Providers erschöpft ist
            p_exhausted = any(p_key in m.lower() for m in exhausted)
            status_badge = "🚨 Cooldown / Limit" if p_exhausted else "🟢 Aktiv & Verfügbar"

            if p_key == "tavily":
                lines.append(f"| **{info['name']}** | `{used:,}` Calls | {status_badge} | {info['limit_desc']} |")
            elif budget == 0:
                # Kein Free-Tier-Kontingent (z.B. Claude) -> kein "X Tokens übrig" vortäuschen
                lines.append(f"| **{info['name']}** | `{used:,}` Tokens | {status_badge} | {info['limit_desc']} |")
            else:
                lines.append(f"| **{info['name']}** | `{used:,}` Tokens | {status_badge} | ca. `{remaining:,}` Tokens übrig ({info['limit_desc']}) |")

        exhausted_details = token_guard.get_exhausted_details()
        if exhausted_details:
            lines.append("\n### 🚨 Aktuell erschöpfte Modelle (Cooldown):")
            lines.append("| Modell | Grund | Verfügbar ab | Verbleibend |")
            lines.append("|---|---|---|---|")
            for d in sorted(exhausted_details, key=lambda x: x["remaining_seconds"]):
                lines.append(
                    f"| `{d['model_name']}` | {d['reason']} | {d['available_at']} Uhr | ca. {d['remaining_seconds']:.0f}s |"
                )

        agent_rows = QuotaEstimator.get_agent_availability()
        if agent_rows:
            lines.append("\n### 👥 Agenten → Modell-Zuordnung & Verfügbarkeit:")
            lines.append("| Agent | Modell | Status |")
            lines.append("|---|---|---|")
            for row in agent_rows:
                status = "🟢 Verfügbar" if row["available"] else f"🚨 Cooldown bis {row['available_at']} Uhr"
                lines.append(f"| `{row['agent_id']}` | `{row['model_name']}` | {status} |")

        if report["models_detail"]:
            lines.append("\n### 📊 Detail-Verbrauch nach Modell (diese Sitzung):")
            lines.append("| Modell | Aufrufe | Prompt Tokens | Completion Tokens | Gesamt |")
            lines.append("|---|---|---|---|---|")
            for m_name, stat in report["models_detail"].items():
                lines.append(
                    f"| `{m_name}` | {stat['total_calls']} | {stat['prompt_tokens']:,} | {stat['completion_tokens']:,} | **{stat['total_tokens']:,}** |"
                )

        # Kumulierte, sitzungsübergreifende Historie (memory/cost_history.py) - anders als
        # alles oben (reiner In-Memory-Zähler dieses Prozesses, bei jedem Neustart wieder bei
        # Null) bleibt das über JEDEN künftigen Prozess-Neustart erhalten. Bewusst nur echte
        # Tokenzahlen, kein geschätzter $-Betrag (siehe memory/cost_history.py-Docstring).
        from memory.cost_history import get_lifetime_totals
        lifetime = get_lifetime_totals()
        lifetime_models = lifetime.get("models", {})
        if lifetime_models:
            lifetime_total = sum(s.get("total_tokens", 0) for s in lifetime_models.values())
            lines.append(
                f"\n### 🗓️ Kumulierter Verbrauch (ALLE Sitzungen seit {lifetime.get('first_recorded_at', '?')[:10]}):"
            )
            lines.append(f"**Gesamt über {lifetime.get('runs_recorded', 0)} Lauf/Läufe:** `{lifetime_total:,}` Tokens\n")
            lines.append("| Modell | Aufrufe | Gesamt |")
            lines.append("|---|---|---|")
            for m_name, stat in sorted(lifetime_models.items(), key=lambda kv: -kv[1].get("total_tokens", 0)):
                lines.append(f"| `{m_name}` | {stat.get('total_calls', 0)} | **{stat.get('total_tokens', 0):,}** |")

        return "\n".join(lines)
