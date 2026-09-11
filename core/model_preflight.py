"""
core/model_preflight.py – Ehrliche Bestandsaufnahme der tatsächlich nutzbaren Modelle

Realer, live reproduzierter Fund (KI-Team-Masterplan-Analyse, 09.09.2026): Ein Aufruf gegen
`claude-sonnet-5` (HEAVY), `gemini-3.8-flash` (STANDARD) und `gemini-3.1-flash-lite` (LITE)
wurde in ALLEN DREI Fällen von ein und demselben Modell beantwortet - `groq:openai/gpt-oss-120b`.
Die gesamte, sorgfältig gepflegte Drei-Stufen-Zuordnung aus config.py war zur Laufzeit also
wirkungslos, ohne dass das an irgendeiner Stelle sichtbar wurde.

Dieses Modul stellt die Frage, die sich das Framework bis dahin nie gestellt hat: *Mit welchen
Modellen arbeite ich gerade eigentlich wirklich?* Ein Team, das das nicht weiß, kann sich auch
nicht sinnvoll selbst optimieren - jede Prompt- oder Rollen-Optimierung misst sonst nur, wie gut
ein unbeabsichtigtes Notfall-Fallback-Modell zufällig abschneidet.

Bewusst ein 1-Token-Ping je Stufe (nicht je Rolle): Es geht um die Frage, ob eine Stufe
überhaupt erreichbar ist, nicht um eine vollständige Kapazitätsmessung. Der Preflight ist
optional und darf einen Start nie blockieren.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import config


@dataclass
class TierStatus:
    """Ergebnis der Verfügbarkeitsprüfung EINER Komplexitätsstufe."""
    tier: str
    requested_model: str
    effective_model: str = ""
    reachable: bool = False
    error: str = ""
    downgrades: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def downgraded(self) -> bool:
        """True, wenn die Stufe zwar antwortet, aber NICHT mit dem angeforderten Modell."""
        from core.llm_factory import is_same_model
        # Kanonischer Vergleich: Provider-Wrapper entfernen ihr Praefix beim Anlegen,
        # sonst gilt jeder Groq-/OpenRouter-Aufruf faelschlich als abgewertet.
        return bool(
            self.reachable
            and self.effective_model
            and not is_same_model(self.effective_model, self.requested_model)
        )

    @property
    def auth_error(self) -> bool:
        """True, wenn die Stufe NICHT erreichbar ist UND die Fehlermeldung nach einem
        ungültigen/abgelehnten API-Key aussieht statt nach fehlendem Key oder Rate-Limit
        (ki_team_verbesserungsanalyse.md, Stufe-0-#1: 'ist der Key gesetzt' und 'funktioniert der
        Key' waren bisher dieselbe Frage - der Preflight-Report zeigte beides als identisches
        generisches '❌ nicht erreichbar', obwohl nur EIN gültiger, echter Live-Ping das
        unterscheiden kann)."""
        from core.llm_factory import is_authentication_error
        return bool(not self.reachable and self.error and is_authentication_error(self.error))


async def check_tier(tier: str, model_name: str, timeout_seconds: float = 30.0) -> TierStatus:
    """
    Schickt einen minimalen Ping an EIN Modell und hält fest, welches Modell tatsächlich
    geantwortet hat. Jede Abwertung innerhalb der Fallback-Kette wird über den Listener aus
    core/llm_factory.py mitgeschnitten.
    """
    from core.llm_factory import LLMFactory, set_model_downgrade_listener

    status = TierStatus(tier=tier, requested_model=model_name)
    set_model_downgrade_listener(
        lambda angefordert, tatsaechlich, grund: status.downgrades.append((angefordert, tatsaechlich, grund))
    )
    try:
        client = LLMFactory.create_for_model(model_name)
        response = await asyncio.wait_for(
            client.generate_with_usage("Antworte ausschliesslich mit: OK"),
            timeout=timeout_seconds,
        )
        status.effective_model = response.model_name or model_name
        status.reachable = True
    except TimeoutError:
        status.error = f"Zeitüberschreitung nach {timeout_seconds:.0f}s"
    except Exception as e:
        status.error = f"{type(e).__name__}: {e}"[:300]
    finally:
        set_model_downgrade_listener(None)
    return status


async def run_model_preflight(timeout_seconds: float = 30.0) -> list[TierStatus]:
    """
    Prüft alle drei Komplexitätsstufen plus den Orchestrator. Bewusst SEQUENTIELL: Parallele
    Pings würden das Minutenlimit unnötig belasten, das core/rate_limiter.py gerade zu schonen
    versucht - und der Preflight läuft einmal beim Start, nicht im heißen Pfad.
    """
    stufen = [
        ("LITE", config.LITE_MODEL),
        ("STANDARD", config.STANDARD_MODEL),
        ("HEAVY", config.HEAVY_MODEL),
        ("ORCHESTRATOR", config.ORCHESTRATOR_MODEL),
    ]
    ergebnisse: list[TierStatus] = []
    for tier, model_name in stufen:
        ergebnisse.append(await check_tier(tier, model_name, timeout_seconds))
    return ergebnisse


def format_preflight_report(ergebnisse: list[TierStatus]) -> str:
    """Kompakte, ehrliche Übersicht für Konsole und Bericht."""
    zeilen = [
        "🔎 Modell-Preflight – was das Team TATSÄCHLICH nutzt",
        "",
        f"{'Stufe':<14} {'angefordert':<28} {'tatsächlich':<28} Status",
        "─" * 88,
    ]
    for r in ergebnisse:
        if not r.reachable:
            status = f"🔑 ungültiger API-Key ({r.error[:40]})" if r.auth_error else f"❌ nicht erreichbar ({r.error[:40]})"
            tatsaechlich = "–"
        elif r.downgraded:
            status = "⚠️  abgewertet"
            tatsaechlich = r.effective_model
        else:
            status = "✅ wie konfiguriert"
            tatsaechlich = r.effective_model
        zeilen.append(f"{r.tier:<14} {r.requested_model:<28} {tatsaechlich:<28} {status}")

    from core.llm_factory import normalize_model_name

    abgewertet = [r for r in ergebnisse if r.downgraded]
    unerreichbar = [r for r in ergebnisse if not r.reachable]
    # Normalisiert vergleichen, sonst gälten "groq:openai/gpt-oss-120b" und
    # "openai/gpt-oss-120b" als zwei verschiedene Modelle und der wichtigste Befund
    # ("alle Stufen laufen auf demselben Modell") bliebe genau dann aus, wenn er zutrifft.
    effektive_modelle = {normalize_model_name(r.effective_model) for r in ergebnisse if r.reachable}

    zeilen.append("")
    if unerreichbar:
        zeilen.append(
            f"❌ {len(unerreichbar)} Stufe(n) gar nicht erreichbar: "
            + ", ".join(r.tier for r in unerreichbar)
        )
    mit_ungueltigem_key = [r for r in unerreichbar if r.auth_error]
    if mit_ungueltigem_key:
        zeilen.append(
            f"🔑 {len(mit_ungueltigem_key)} Stufe(n) lehnen den konfigurierten API-Key ab "
            "(falsch oder widerrufen, nicht nur fehlend) - Key in .env prüfen/erneuern: "
            + ", ".join(r.tier for r in mit_ungueltigem_key)
        )
    if abgewertet:
        zeilen.append(
            f"⚠️  {len(abgewertet)} Stufe(n) antworten mit einem ANDEREN Modell als konfiguriert. "
            "Prüfe den passenden API-Key bzw. das Tageskontingent."
        )
    if len(effektive_modelle) == 1 and len(ergebnisse) > 1:
        # Genau der Zustand, der die Analyse ausgelöst hat: drei "verschiedene" Stufen, ein Modell.
        zeilen.append(
            f"🔴 ALLE Stufen laufen auf demselben Modell (`{next(iter(effektive_modelle))}`) – "
            "die Modell-Differenzierung des Teams ist damit zur Laufzeit wirkungslos."
        )
    if not abgewertet and not unerreichbar:
        zeilen.append("✅ Alle Stufen antworten mit dem konfigurierten Modell.")
    return "\n".join(zeilen)
