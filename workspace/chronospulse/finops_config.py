# finops_config.py
from pydantic import BaseModel, Field

class LLMBudgetLimits(BaseModel):
    monthly_cap_usd: float = Field(default=100.0, description="Hard limit for LLM costs")
    daily_token_limit: int = Field(default=1_000_000, description="Safety limit per day")
    model_fallback_enabled: bool = True

class FinOpsConfig:
    # Aktuelle Strategie: Kostenoptimierung durch Caching & Modell-Routing
    STRATEGY = "Tiered-Model-Usage"
    CACHE_TTL_SECONDS = 3600
    
    @staticmethod
    def get_cost_estimate(tokens: int, model: str = "gpt-4o-mini") -> float:
        # Vereinfachte Kalkulation für Planung
        pricing = {"gpt-4o-mini": 0.00015, "gpt-4o": 0.005}
        return (tokens / 1000) * pricing.get(model, 0.001)
