import json
import os

from openai import AsyncOpenAI

from app.schemas.ai_analysis import IncidentPayload, WorkflowRecommendation
from app.utils.resilience import resilience_wrapper

# Dummy-Key für Tests, falls nicht gesetzt
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "sk-dummy"))

def _analyze_incident_fallback(incident: IncidentPayload, **_: object) -> WorkflowRecommendation:
    """Typsicherer Fallback, wenn der Circuit Breaker offen ist (AI-Service nicht erreichbar)."""
    return WorkflowRecommendation(
        incident_id=incident.incident_id,
        severity="unknown",
        analysis="AI-Service aktuell nicht verfügbar (Circuit Breaker offen). Manuelle Prüfung erforderlich.",
        suggested_workflow={
            "action": "manual_review_required",
            "confidence": 0.0,
            "reasoning": "Fallback: AI-Analyse konnte wegen offenem Circuit Breaker nicht durchgeführt werden.",
        },
    )


@resilience_wrapper(fallback_factory=_analyze_incident_fallback)
async def analyze_incident(incident: IncidentPayload) -> WorkflowRecommendation:
    system_prompt = open("docs/prompts/incident_analyst_prompt.md", encoding="utf-8").read()
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": incident.model_dump_json()}
        ],
        response_format={"type": "json_object"}
    )
    
    data = json.loads(response.choices[0].message.content)
    return WorkflowRecommendation(**data)
