"""
core/root_cause_analyst.py – Automatisierter Root-Cause-Analyst nach gescheiterten Läufen

Nutzerwunsch (Gesamtsystem-Analyse 2026-09-14, Punkt 3.1 "Automatisierter Root-Cause-Analyst",
größte identifizierte Lücke zum Ziel "das KI-Team soll mit jedem gemachten Fehler dazulernen"):

Die vier Tiefenanalysen, die zu den wichtigsten Framework-Fixes der letzten Woche geführt haben
(`ki_team_schwachstellen_und_fehleranalyse_{devpulse,aethermesh,chronospulse,hyperionsentinel}_
202609*.md` im Projekt-Root - z.B. das "Verification Reserve Paradox" in agents/orchestrator/
__init__.py oder die "Ghost-Frontend"-Schwachstelle in core/verifier/completeness.py), sind
NIRGENDS im Code als automatisierter Schritt verankert. Sie entstanden ausschließlich in
manuellen Analyse-Sitzungen, in denen jemand logs/runs/*.jsonl, logs/verification/*.log UND den
tatsächlichen Projekt-/Framework-Code zusammen liest.

Der automatisch nach JEDEM Lauf laufende Retrospektive-/Trainer-Schritt (agents/orchestrator/
retrospective.py) bekommt dagegen nur einen auf ~1500-2000 Zeichen gekappten PROSA-Auszug ohne
jeden Tool-Zugriff (kein project_dir/allow_tools an dessen AgentTask) - das reicht für
oberflächliches Prompt-Feedback, aber nicht für Funde, die echte Logs und echten Code
nebeneinander lesen müssen.

Dieses Modul schließt genau diese Lücke, OHNE den bestehenden, immer laufenden Trainer-Schritt
zu verändern: should_trigger() entscheidet rein deterministisch (kein LLM-Aufruf, dieselbe
Kosten-Nutzen-Linie wie core/optimization_advisor.py.MIN_SAMPLE_SIZE), ob sich eine
KOSTENPFLICHTIGE Tiefenanalyse überhaupt lohnt - nur bei echten Fehlschlägen/Abbrüchen, nicht
bei jedem Lauf. run_analysis() legt dann eine EIGENE AgentTask mit `project_dir=BASE_DIR` und
`tools_read_only=True` an (siehe core/agent_toolbox.py._is_sensitive_name für den .env-Schutz,
der dabei automatisch greift) - der Agent kann damit sowohl den generierten Projekt-Code
(workspace/<slug>/) als auch den Framework-Code selbst (agents/, core/) lesen, genau wie eine
manuelle Analyse-Sitzung es tut.

Bewusst NUR ein Vorschlags-Mechanismus, KEINE automatische Code-Änderung (dieselbe Linie wie
core/roadmap_advisor.py/core/optimization_advisor.py): Framework-Änderungen verdienen ein
menschliches Review. record_findings_as_tickets() legt deshalb Tickets mit source=TICKET_SOURCE
an, das bewusst NICHT in core/backlog_worker.py._AUTONOMOUS_SOURCES enthalten ist.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import BASE_DIR, MEMORY_DIR
from core.backlog_store import upsert_ticket
from core.message_bus import AgentTask
from core.team_memory import record_lesson

TICKET_SOURCE = "root_cause_analysis"

# Folgeanalyse 2026-09-14, Befund 2: should_trigger() weiter unten ist bewusst rein
# deterministisch UND zustandslos (kein I/O, siehe dortiger Docstring) und löst deshalb bei
# JEDEM einzelnen Lauf mit `not verification_ok and files_written > 0` erneut aus - ein
# chronisch scheiterndes Projekt (real beobachtet: drei aufeinanderfolgende ecochef-Läufe an
# einem Nachmittag) hätte damit bei JEDEM Lauf den vollen, werkzeugbasierten LLM-Aufruf mit
# Zugriff auf das gesamte Repository ausgelöst - anders als core/optimization_advisor.py, das
# vor einem Vorschlag eine statistisch tragfähige Mindest-Stichprobe verlangt. Der Cooldown
# sitzt bewusst in run_analysis() (dem einzigen Ort, an dem der eigentliche kostenpflichtige
# Aufruf passiert), NICHT in should_trigger() - so bleibt should_trigger() weiterhin pur
# testbar, und JEDER Aufrufer von run_analysis() profitiert automatisch vom Kostenschutz.
ROOT_CAUSE_ANALYSIS_STATE_FILE = Path(MEMORY_DIR) / "root_cause_analysis_state.json"
# 6 Stunden: lang genug, um mehrere Läufe DERSELBEN Sitzung an einem hartnäckig scheiternden
# Projekt (wie die drei ecochef-Läufe binnen weniger Stunden) auf EINE Tiefenanalyse zu
# begrenzen, kurz genug, dass ein tatsächlich am nächsten Tag fortgesetzter Versuch wieder
# frisch analysiert wird, statt auf unbestimmte Zeit stummgeschaltet zu bleiben.
ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS = 6 * 60 * 60


def _load_analysis_state() -> dict[str, float]:
    if not ROOT_CAUSE_ANALYSIS_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(ROOT_CAUSE_ANALYSIS_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_analysis_state(state: dict[str, float]) -> None:
    try:
        ROOT_CAUSE_ANALYSIS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROOT_CAUSE_ANALYSIS_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _recently_analyzed(project_slug: str) -> bool:
    last = _load_analysis_state().get(project_slug)
    return last is not None and (time.time() - last) < ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS


def _record_analysis_attempt(project_slug: str) -> None:
    """Wird VOR dem eigentlichen (teuren) Aufruf geschrieben, nicht erst nach Erfolg - der
    Cooldown soll den Token-Verbrauch des VERSUCHS begrenzen, unabhängig davon, ob am Ende ein
    verwertbarer Befund dabei herauskam."""
    state = _load_analysis_state()
    state[project_slug] = time.time()
    _save_analysis_state(state)

# Wie viele der letzten Zeichen jeder Rohdatei (Lauf-Log/Verifikations-Log) in den Prompt
# aufgenommen werden - dieselbe "die letzten N Zeichen tragen die eigentliche Ursache"-Faustregel
# wie interface/cli.py's `traceback.format_exc()[-1000:]`, nur großzügiger bemessen, weil dies
# eine bewusst SELTENE, gezielte Tiefenanalyse ist (siehe should_trigger()), kein Aufruf, der bei
# jedem Lauf anfällt. Deckelt gleichzeitig den Tokenverbrauch dieses einen zusätzlichen Aufrufs
# nach oben ab, unabhängig davon, wie riesig ein einzelnes Verifikations-Log werden kann (siehe
# core/run_logger.py.MAX_VERIFICATION_CHARS_PER_ENTRY).
MAX_EVIDENCE_CHARS_PER_LOG = 12_000

# Ticket-Detail-Obergrenze - dieselbe Konvention wie core/project_status.py.MAX_FAILURE_DETAIL_
# CHARS (dort 500) bzw. interface/cli.py (dort 1200 für Exception+Traceback zusammen), hier
# etwas großzügiger, weil ein Root-Cause-Befund Titel, Ursache UND Empfehlung in einem Detail
# trägt.
MAX_FINDING_DETAIL_CHARS = 1500

# Folgeanalyse 2026-09-14 ("kritischer Befund 1"): die ursprüngliche Version verlangte ZWISCHEN
# den vier Feldern (Kategorie/Titel/Root Cause/Empfehlung) exakt EINEN Zeilenumbruch, keinen
# leeren dazwischen. Tatsächlich ausgeführter Test mit einer realistischeren, Leerzeilen-
# durchsetzten LLM-Antwort (Standard-Markdown-Stil für fett hervorgehobene Label, den praktisch
# jedes Modell verwendet, unabhängig vom Prompt-Beispiel ohne Leerzeilen) ergab 0 statt der
# erwarteten Befunde - das gesamte Feature wäre dadurch in der Praxis vermutlich fast wirkungslos
# gewesen, obwohl der teure Werkzeug-Loop bereits gelaufen war. core/roadmap_advisor.py._PROPOSAL_
# RE umgeht dieses Problem, indem es zeilenweise arbeitet statt einen einzigen durchgehenden
# Block-Regex zu verlangen - hier wird derselbe Grundgedanke auf ein Mehrzeilen-Format übertragen:
# _BEFUND_HEADER_RE zerlegt den Bericht zunächst in Blöcke je "### Befund N", danach lokalisiert
# _FIELD_LABEL_RE INNERHALB eines Blocks die Position JEDES Feld-Labels (in BELIEBIGER Reihenfolge,
# mit beliebig vielen Leerzeilen dazwischen) und der Text zwischen zwei Label-Positionen wird als
# Feldinhalt übernommen - robust gegen Leerzeilen, abweichende Reihenfolge und fehlende Doppelpunkte.
_BEFUND_HEADER_RE = re.compile(r"#{2,4}\s*Befund\s*\d+\s*", re.IGNORECASE)
# ^[ \t]* (nicht \s*) verankert das Label am Zeilenanfang (Leerzeilen/Einrückung erlaubt, aber
# KEIN Zeilenumbruch davor) - verhindert, dass "Empfehlung" o.Ä. zufällig MITTEN in einem Satz
# (z.B. innerhalb des Root-Cause-Fließtexts) fälschlich als neues Feld erkannt wird.
_FIELD_LABEL_RE = re.compile(
    r"^[ \t]*\**\s*(Kategorie|Titel|Root\s*Cause|Empfehlung)\s*\**\s*:?\s*\**",
    re.IGNORECASE | re.MULTILINE,
)
_FIELD_KEY_MAP = {"kategorie": "category", "titel": "title", "rootcause": "root_cause", "empfehlung": "recommendation"}
_NORMALIZE_TITLE_RE = re.compile(r"[^a-z0-9]+")


def _parse_fields(block: str) -> dict[str, str]:
    """Lokalisiert jedes bekannte Feld-Label im Block (Reihenfolge/Leerzeilen egal) und
    übernimmt den Text bis zum NÄCHSTEN Label (oder Blockende) als Feldinhalt. Ein doppelt
    vorkommendes Label behält den ERSTEN Treffer (ein Modell, das ausversehen "Empfehlung"
    zweimal schreibt, soll nicht den ursprünglichen Inhalt stillschweigend überschreiben)."""
    matches = list(_FIELD_LABEL_RE.finditer(block))
    fields: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = _FIELD_KEY_MAP.get(re.sub(r"\s+", "", m.group(1).lower()))
        if not key or key in fields:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        fields[key] = " ".join(block[m.end():end].split())
    return fields

_TASK_PROMPT = """Du bist der Root-Cause-Analyst des Teams (siehe agents/agent_trainer_agent.py-
Rolle: Principal AI Alignment Specialist & Meta-Cognition). Dir liegen die ROHEN Logdaten und
Ergebnisse EINES gescheiterten oder abgebrochenen Laufs vor. Deine Aufgabe ist EXAKT die einer
manuellen Tiefenanalyse-Sitzung (wie die vorhandenen `ki_team_schwachstellen_und_fehleranalyse_*.
md`-Berichte im Projekt-Root): finde die WIRKLICHE Ursache, nicht nur das Symptom.

Nutze deine Werkzeuge (read_file/search_code/list_files, NUR LESEND):
1. Lies die relevanten Stellen im generierten Projekt-Code (workspace/<projekt>/...), wenn der
   Fehler dort liegt.
2. Lies die relevanten Stellen im FRAMEWORK-Code selbst (agents/..., core/...), wenn die Ursache
   im Orchestrator/Verifier/einer Agenten-Rolle liegt, nicht im generierten Projekt.
3. Unterscheide klar: ist das ein Fehler des generierten PROJEKT-Codes (ein Agent hat schlecht
   gearbeitet) oder eine strukturelle Schwachstelle im FRAMEWORK selbst (ein Bug, der jedem
   künftigen Projekt genauso passieren würde)?

Antworte NACH einer kurzen Einleitung (max. 3 Sätze) mit 1 bis 4 Befunden in GENAU diesem
Format, jeder Befund als eigener Block, keine Abweichung (wird maschinell geparst):

### Befund 1
**Kategorie:** framework ODER projekt
**Titel:** Kurzer, prägnanter Titel (max. 12 Wörter)
**Root Cause:** Ein bis drei Sätze, WARUM der Fehler wirklich passiert ist (nicht nur was).
**Empfehlung:** Ein bis drei Sätze, was konkret geändert werden sollte (Datei/Funktion nennen,
wenn bekannt).

### Befund 2
(usw., nur so viele Befunde wie tatsächlich durch echte Evidenz gestützt sind - lieber ein
gut belegter Befund als drei geratene.)"""


@dataclass
class RootCauseTrigger:
    """Ergebnis von should_trigger() - `reason` ist ausschließlich für Logging/Statusmeldungen
    gedacht, niemals maschinell weiterverarbeitet."""
    should_run: bool
    reason: str = ""


def should_trigger(
    *,
    verification_ok: bool,
    files_written: int,
    aborted: bool = False,
    recurring_signature_seen_before: bool = False,
) -> RootCauseTrigger:
    """Rein deterministisch (kein LLM-Aufruf nötig - dieselbe Philosophie wie core/optimization_
    advisor.py, das bereits vorhandene harte Zahlen auswertet statt zu interpretieren).

    Löst NICHT bei jedem Lauf aus, nur bei echten Warnsignalen, damit der zusätzliche
    (kostenpflichtige) LLM-Aufruf sich lohnt:
    - `aborted`: der Lauf endete durch eine unbehandelte Exception (siehe Orchestrator.process()
      und dessen orchestrator_crash-Ticket) - IMMER analysewürdig, unabhängig von files_written,
      da ein Absturz per Definition keine sinnvolle Verifikation mehr erreicht hat.
    - `not verification_ok and files_written > 0`: echte Arbeit wurde geleistet, aber die
      Verifikation blieb rot - genau der Fall, der bei devpulse/chronospulse/hyperionsentinel zu
      den wertvollsten manuellen Funden führte. `files_written == 0` wird bewusst ausgeschlossen:
      das ist bereits ein eigenständiges, andersartiges Signal (false_success_no_source_files in
      agents/orchestrator/retrospective.py), keine Verifikationsursache, die sich im Code
      nachvollziehen ließe.
    - `recurring_signature_seen_before`: dasselbe Fehlermuster trat schon einmal an diesem
      Projekt auf (has_repeated_failure() in agents/orchestrator/__init__.py) - der reguläre
      Fix-/Governance-Loop hat es offenbar NICHT dauerhaft gelöst, ein zweiter, tieferer Blick
      lohnt sich unabhängig vom aktuellen files_written-Stand.
    """
    if aborted:
        return RootCauseTrigger(True, "Lauf durch unbehandelte Exception abgebrochen")
    if recurring_signature_seen_before:
        return RootCauseTrigger(True, "Wiederkehrendes Fehlermuster erneut an diesem Projekt aufgetreten")
    if not verification_ok and files_written > 0:
        return RootCauseTrigger(True, "Verifikation nicht bestanden trotz geschriebener Dateien")
    return RootCauseTrigger(False, "Kein Warnsignal - Tiefenanalyse würde sich nicht lohnen")


def _tail(text: str, max_chars: int) -> str:
    """Die letzten `max_chars` Zeichen - die eigentliche Fehlerursache steht bei Logs praktisch
    immer am ENDE (letzter Testlauf, letzter Absturz), nicht am Anfang (siehe Moduldocstring)."""
    if not text or len(text) <= max_chars:
        return text
    return "… [gekürzt, nur das Ende ist erhalten] …\n" + text[-max_chars:]


def _read_capped(path: Path | str | None, max_chars: int = MAX_EVIDENCE_CHARS_PER_LOG) -> str:
    """Best-effort: eine fehlende/unlesbare Datei liefert einen leeren String statt die
    Analyse zum Absturz zu bringen - dieselbe Großzügigkeit wie core/run_logger.py."""
    if not path:
        return ""
    try:
        return _tail(Path(path).read_text(encoding="utf-8", errors="replace"), max_chars)
    except OSError:
        return ""


def gather_evidence(
    *,
    project_slug: str,
    user_request: str,
    verification_summary: str = "",
    run_log_path: Path | str | None = None,
    verification_log_path: Path | str | None = None,
) -> str:
    """Baut den Kontext für die Tiefenanalyse aus den ROHEN Artefakten des Laufs - genau das,
    was eine manuelle Analyse-Sitzung liest, statt der stark gekürzten Prosa-Auszüge, die der
    reguläre (immer laufende) Retrospektive-/Trainer-Schritt bekommt."""
    parts = [f"PROJEKT: {project_slug}\n\nURSPRÜNGLICHE AUFGABE:\n{user_request[:1000]}\n"]
    if verification_summary.strip():
        parts.append(f"\nVERIFIKATIONS-ZUSAMMENFASSUNG:\n{verification_summary.strip()[:3000]}\n")
    run_log_text = _read_capped(run_log_path)
    if run_log_text:
        parts.append(f"\nROHES LAUF-LOG (JSONL, eine Zeile je Ereignis):\n{run_log_text}\n")
    verification_log_text = _read_capped(verification_log_path)
    if verification_log_text:
        parts.append(f"\nROHES VERIFIKATIONS-LOG (pip/pytest/npm-Ausgabe):\n{verification_log_text}\n")
    return "".join(parts)


def build_analysis_task(project_slug: str, evidence: str) -> AgentTask:
    """`project_dir=BASE_DIR` (nicht nur workspace/<projekt>) gibt dem Agenten bewusst Zugriff
    auf BEIDES: den generierten Projekt-Code (workspace/<projekt>/...) UND den Framework-Code
    selbst (agents/, core/) - die meisten wertvollen manuellen Funde (Verification Reserve
    Paradox, Ghost-Frontend, falsches Fehler-Routing) waren FRAMEWORK-Bugs, kein
    workspace/-Scope hätte sie sichtbar gemacht. `tools_read_only=True` verhindert dabei jede
    Schreib-/Ausführungs-Aktion (core/agent_toolbox.py blockt zusätzlich .env/*.pem/*secret*
    unabhängig vom Modus)."""
    return AgentTask(
        task_id=f"root_cause_analysis_{project_slug}",
        agent_id="agent_trainer",
        description=_TASK_PROMPT,
        context=evidence,
        project_dir=str(BASE_DIR),
        allow_tools=True,
        tools_read_only=True,
    )


def extract_findings(report_text: str) -> list[dict[str, str]]:
    """Parst die ### Befund N-Blöcke - best effort: ein Block ohne Titel/Root-Cause/Empfehlung
    wird stillschweigend übersprungen (dieselbe Toleranz wie core/roadmap_advisor.py._parse_
    proposals gegenüber frei formuliertem LLM-Text), statt die ganze Analyse zu verwerfen.
    Fehlt "Kategorie" (Modell hat das Label ausgelassen), gilt der Befund sicherheitshalber als
    "projekt" (niedrigere Priorität in record_findings_as_tickets()) statt als "framework"."""
    findings = []
    for block in _BEFUND_HEADER_RE.split(report_text)[1:]:  # [0] ist die Einleitung vor "### Befund 1"
        fields = _parse_fields(block)
        title = fields.get("title", "").strip(" *`\"'")
        root_cause = fields.get("root_cause", "")
        recommendation = fields.get("recommendation", "")
        if not title or not root_cause or not recommendation:
            continue
        findings.append({
            "category": "framework" if "framework" in fields.get("category", "").lower() else "projekt",
            "title": title,
            "root_cause": root_cause,
            "recommendation": recommendation,
        })
    return findings


def _ticket_id_for(project_slug: str, title: str) -> str:
    """Stabil über wiederholte Läufe MIT DEMSELBEN Befund hinweg (normalisierter Titel, kein
    Zeitstempel/Hash) - dieselbe Update-statt-Neuanlage-Semantik wie core/roadmap_advisor.py.
    _ticket_id_for(): ein wiederkehrender Befund aktualisiert sein bestehendes Ticket
    (upsert_ticket()), statt bei jedem erneuten Auftreten ein Duplikat anzulegen."""
    normalized = _NORMALIZE_TITLE_RE.sub("-", title.lower()).strip("-")[:60] or "befund"
    return f"root-cause-{project_slug}-{normalized}"


def record_findings_as_tickets(project_slug: str, findings: list[dict[str, str]]) -> list[str]:
    """Legt für jeden Befund ein eigenes, NICHT-autonomes Ticket an (source=TICKET_SOURCE - siehe
    core/backlog_worker.py._AUTONOMOUS_SOURCES: ein Framework- oder Projekt-Root-Cause-Befund ist
    ein Vorschlag, den ein Mensch reviewen soll, kein Auftrag, den --work-backlog selbstständig
    umsetzen darf) UND spiegelt ihn zusätzlich als Team-Lektion (core/team_memory.py), damit er
    auch OHNE das Dashboard/Backlog-Board künftigen Agenten-Prompts direkt mitgegeben wird."""
    ticket_ids: list[str] = []
    for finding in findings:
        title, category = finding["title"], finding["category"]
        detail = (
            f"[{category}] Root Cause: {finding['root_cause']}\n\nEmpfehlung: {finding['recommendation']}"
        )[:MAX_FINDING_DETAIL_CHARS]
        ticket_id = _ticket_id_for(project_slug, title)
        try:
            upsert_ticket(
                ticket_id=ticket_id,
                title=f"Root-Cause-Befund ({category}): {title}",
                source=TICKET_SOURCE,
                status="blocked" if category == "framework" else "todo",
                project_slug=project_slug,
                priority=1 if category == "framework" else 2,
                detail=detail,
            )
            ticket_ids.append(ticket_id)
        except Exception:
            # Ein fehlgeschlagenes Einzel-Ticket darf die übrigen Befunde nicht verwerfen -
            # dasselbe Best-effort-Prinzip wie core/optimization_advisor.py.record_unused_
            # agent_tickets().
            continue
        try:
            record_lesson(project_slug, "root_cause_analysis", f"{title}: {finding['root_cause']}")
        except Exception:
            pass
    return ticket_ids


@dataclass
class RootCauseAnalysisReport:
    """Ergebnis eines run_analysis()-Durchlaufs."""
    project_slug: str
    findings: list[dict[str, str]] = field(default_factory=list)
    ticket_ids: list[str] = field(default_factory=list)
    raw_content: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


async def run_analysis(
    orchestrator,
    *,
    project_slug: str,
    user_request: str,
    verification_summary: str = "",
    run_log_path: Path | str | None = None,
    verification_log_path: Path | str | None = None,
) -> RootCauseAnalysisReport:
    """Hauptzugang: baut die Evidenz, lässt den agent_trainer sie MIT echtem read-only
    Tool-Zugriff analysieren und persistiert die extrahierten Befunde als Tickets + Team-
    Lektionen. `orchestrator`: eine bereits initialisierte Orchestrator-Instanz - wiederverwendet
    (wie core/roadmap_advisor.py.propose_next_steps), damit derselbe Aufruf sowohl aus einem
    laufenden process()-Aufruf als auch aus einem späteren Batch-Skript (analog `python main.py
    --check-deployments`) funktioniert, ohne zwei Codepfade zu brauchen.

    Bricht VOR dem eigentlichen (kostenpflichtigen) Aufruf ab, wenn für `project_slug` innerhalb
    von ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS bereits eine Analyse versucht wurde (siehe
    Modul-Docstring, Folgeanalyse 2026-09-14, Befund 2)."""
    if _recently_analyzed(project_slug):
        return RootCauseAnalysisReport(
            project_slug=project_slug,
            error=(
                f"Übersprungen: '{project_slug}' wurde innerhalb der letzten "
                f"{ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS // 3600}h bereits analysiert (Cooldown)."
            ),
        )
    _record_analysis_attempt(project_slug)

    evidence = gather_evidence(
        project_slug=project_slug, user_request=user_request,
        verification_summary=verification_summary,
        run_log_path=run_log_path, verification_log_path=verification_log_path,
    )
    task = build_analysis_task(project_slug, evidence)
    try:
        result = await orchestrator._run_single_agent(task)
    except Exception as e:
        return RootCauseAnalysisReport(project_slug=project_slug, error=str(e))

    if not result.success or not result.content:
        return RootCauseAnalysisReport(
            project_slug=project_slug, error=result.error or "Keine Antwort vom Root-Cause-Analysten.",
        )

    findings = extract_findings(result.content)
    if not findings:
        return RootCauseAnalysisReport(
            project_slug=project_slug, raw_content=result.content,
            error="Antwort enthielt keine im erwarteten Format erkennbaren Befunde.",
        )

    ticket_ids = record_findings_as_tickets(project_slug, findings)
    return RootCauseAnalysisReport(
        project_slug=project_slug, findings=findings, ticket_ids=ticket_ids, raw_content=result.content,
    )
