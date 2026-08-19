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
    def get_detailed_report() -> dict[str, Any]:
        summary = token_guard.get_summary()
        models = summary.get("models", {})
        grand_total = summary.get("grand_total_tokens", 0)
        exhausted = summary.get("exhausted_models", [])

        # Aufteilung nach Providern
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

        return {
            "grand_total_tokens": grand_total,
            "models_detail": models,
            "provider_usage": provider_usage,
            "exhausted_models": exhausted,
            "free_tier_limits": FREE_TIER_LIMITS,
        }

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

        if report["models_detail"]:
            lines.append("\n### 📊 Detail-Verbrauch nach Modell:")
            lines.append("| Modell | Aufrufe | Prompt Tokens | Completion Tokens | Gesamt |")
            lines.append("|---|---|---|---|---|")
            for m_name, stat in report["models_detail"].items():
                lines.append(
                    f"| `{m_name}` | {stat['total_calls']} | {stat['prompt_tokens']:,} | {stat['completion_tokens']:,} | **{stat['total_tokens']:,}** |"
                )

        return "\n".join(lines)
