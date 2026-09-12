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
    ergebnisse.extend(await check_independent_failover_providers(timeout_seconds))
    return ergebnisse


# Realer Fund (logs/runs/20260912_082145_sentinelgrid.jsonl): DeepSeek ("Insufficient Balance")
# und OpenRouter ("requires more credits") werden NIE als LITE/STANDARD/HEAVY-Primärstufe
# angefragt, sondern nur lazy als Cross-Provider-Ausweichkette (core.llm_factory.
# _INDEPENDENT_FAILOVER_MODELS), NACHDEM Groq/Gemini bereits gescheitert sind. Ein leeres
# Guthaben wurde deshalb erst mitten im Lauf entdeckt - JEDER Agent, der in diese Kette lief,
# verschwendete einen vollen Hop auf einen Account, der schon zu Laufbeginn erkennbar leer war.
# Diese beiden Provider werden deshalb zusätzlich beim Preflight direkt angepingt (nur wenn ein
# Key konfiguriert ist), damit ein bekannt leeres Guthaben SOFORT über token_guard.
# mark_model_exhausted() markiert ist, bevor der erste Agent überhaupt startet.
async def check_independent_failover_providers(timeout_seconds: float = 30.0) -> list[TierStatus]:
    """Pingt DeepSeek/OpenRouter direkt an (nur mit konfiguriertem Key) - siehe Modul-Kommentar
    über run_model_preflight(). Der eigentliche Aufruf über LLMFactory ruft bei einem
    Guthaben-Fehler bereits token_guard.mark_model_exhausted() auf (core/llm_factory.py,
    DeepSeekClient/OpenRouterClient), sodass hier keine zusätzliche Markierung nötig ist - der
    Preflight sorgt lediglich dafür, dass diese Markierung VOR dem ersten Agenten steht statt
    erst nach dessen vergeblichem Hop.

    Die Keys werden bewusst live aus `config` gelesen (nicht als Modul-Konstante gecacht), damit
    ein zur Laufzeit gesetzter/entfernter Key ohne Prozess-Neustart wirkt."""
    kandidaten = (
        (config.DEEPSEEK_API_KEY, "deepseek:deepseek-chat"),
        (config.OPENROUTER_API_KEY, "openrouter:openrouter/auto"),
    )
    ergebnisse: list[TierStatus] = []
    for api_key, model_name in kandidaten:
        if not api_key:
            continue
        tier = model_name.split(":", 1)[0].upper()
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


# ── Lauf-Empfehlung (Sicherheitsmaßnahme, KI-Team-Gesamtanalyse) ───────────────────────────
# Der reine Preflight-Bericht oben listet nur auf, WAS gerade erreichbar ist - er beantwortet
# nicht die eigentliche Frage, die sich ein Nutzer VOR dem Tippen einer neuen Projektaufgabe
# stellt: "Lohnt sich das gerade überhaupt, oder verbrenne ich nur Zeit/Tokens an einem Team,
# das ohnehin auf schwächste Fallback-Modelle abrutscht oder komplett steht?" Realer Fund
# (CertPulse, 12.09.2026, fehleranalyse_ki_team.md): ein Lauf mit 319.244 verbrauchten Tokens
# lieferte am Ende NICHTS ab - wäre die eingeschränkte Verfügbarkeit VOR dem Start sichtbar
# gewesen, hätte der Nutzer den Lauf gar nicht erst gestartet oder zumindest gewusst, worauf
# er sich einlässt.
#
# Nur die drei Komplexitätsstufen + der Orchestrator zählen für die Ampel - DeepSeek/
# OpenRouter (siehe check_independent_failover_providers) sind optionale Cross-Provider-
# Ausweichrouten, kein Kernbestandteil der Stufen-Zuordnung; ihr Ausfall allein macht das
# Team nicht arbeitsunfähig.
CORE_TIERS: tuple[str, ...] = ("LITE", "STANDARD", "HEAVY", "ORCHESTRATOR")


@dataclass
class RunReadiness:
    """Ampel-Einschätzung: lohnt sich JETZT ein neuer Projektlauf?"""
    level: str  # "green" | "yellow" | "red"
    headline: str
    reasons: list[str] = field(default_factory=list)

    @property
    def should_confirm(self) -> bool:
        """True, wenn der Nutzer vor dem Start eine explizite Bestätigung sehen sollte
        (rot: nichts erreichbar) statt sich nur informell zu informieren (gelb: geht, aber
        eingeschränkt)."""
        return self.level == "red"


def assess_run_readiness(ergebnisse: list[TierStatus]) -> RunReadiness:
    """
    Verdichtet die Preflight-Ergebnisse zu einer einfachen Drei-Stufen-Empfehlung:

    - 🔴 rot: KEINE der Kernstufen (LITE/STANDARD/HEAVY/ORCHESTRATOR) antwortet überhaupt -
      das Team ist faktisch arbeitsunfähig, ein Start würde nur an der ersten Agenten-
      Anfrage scheitern.
    - 🟡 gelb: mindestens eine Kernstufe antwortet, aber nicht alle, oder mindestens eine
      antwortet mit einem anderen als dem konfigurierten Modell (stille Abwertung) - ein
      Lauf ist möglich, aber mit reduzierter Qualität oder auf schwächeren Fallback-Modellen
      zu rechnen.
    - 🟢 grün: alle Kernstufen antworten mit dem jeweils konfigurierten Modell - nichts
      spricht gegen einen Start.

    Bewusst NUR eine Empfehlung, kein hartes Verbot: `core/token_guard.py` und der Fast
    Circuit Breaker (`agents/orchestrator/department.py`) bleiben die eigentliche
    Absicherung WÄHREND eines Laufs; dies hier ist ausschließlich die Vorab-Information, die
    dem Nutzer VOR dem Tippen einer Aufgabe fehlte.
    """
    core = [r for r in ergebnisse if r.tier in CORE_TIERS]
    if not core:
        # Sollte praktisch nie vorkommen (run_model_preflight() liefert immer die vier
        # Kernstufen) - defensiv trotzdem kein Absturz, nur eine ehrliche "unbekannt"-Lage.
        return RunReadiness(level="yellow", headline="⚪ Keine Kernstufen geprüft - Einschätzung nicht möglich.")

    unreachable = [r for r in core if not r.reachable]
    downgraded = [r for r in core if r.downgraded]
    auth_errors = [r for r in core if r.auth_error]
    reachable = [r for r in core if r.reachable]

    if not reachable:
        return RunReadiness(
            level="red",
            headline=(
                "🔴 KEINE der Kernstufen (LITE/STANDARD/HEAVY/ORCHESTRATOR) ist gerade erreichbar - "
                "aktuell lohnt sich KEIN neuer Projektlauf."
            ),
            reasons=[
                f"❌ {r.tier}: {r.error}" + (" (ungültiger/abgelehnter API-Key)" if r.auth_error else "")
                for r in unreachable
            ],
        )

    reasons: list[str] = []
    if unreachable:
        reasons.append(
            f"❌ {len(unreachable)} von {len(core)} Kernstufen nicht erreichbar: "
            + ", ".join(r.tier for r in unreachable)
        )
    if downgraded:
        reasons.append(
            f"⚠️  {len(downgraded)} Kernstufe(n) antworten mit einem ANDEREN Modell als konfiguriert: "
            + ", ".join(f"{r.tier}→{r.effective_model}" for r in downgraded)
        )
    if auth_errors:
        reasons.append(
            f"🔑 {len(auth_errors)} Kernstufe(n) lehnen den konfigurierten API-Key ab: "
            + ", ".join(r.tier for r in auth_errors)
        )

    if unreachable or downgraded:
        return RunReadiness(
            level="yellow",
            headline=(
                "🟡 Team eingeschränkt arbeitsfähig - ein Lauf ist möglich, aber mit reduzierter "
                "Qualität oder auf schwächeren Fallback-Modellen zu rechnen."
            ),
            reasons=reasons,
        )

    return RunReadiness(
        level="green",
        headline="🟢 Alle Kernstufen erreichbar und wie konfiguriert - ein Projektlauf lohnt sich jetzt.",
    )


def format_run_readiness(readiness: RunReadiness) -> str:
    """Kompakter Text-Block für Konsole/Dashboard, passend zur Ampel aus assess_run_readiness()."""
    zeilen = [readiness.headline]
    zeilen.extend(f"  {r}" for r in readiness.reasons)
    return "\n".join(zeilen)
