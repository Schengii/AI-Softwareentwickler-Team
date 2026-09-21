"""
agents/orchestrator/retrospective.py – RetrospectiveMixin: Retrospektive nach Laufende sowie
die Selbstoptimierungs-Schleife des Agent-Trainers (extrahiert & speichert Lern-Regeln
persistent, damit alle Agenten aus vergangenen Fehlern/Läufen lernen).
"""

import json
import re
from collections.abc import Callable

from config import TRAINER_HIGH_USAGE_TOKENS_PER_CALL, TRAINER_MAX_TOOL_ITERATIONS
from core.message_bus import AgentResult, AgentTask
from core.project_status import has_repeated_failure
from core.provider_exhaustion import FAILURE_CLASS_PROVIDER_EXHAUSTED
from core.team_memory import record_lesson

# Team-Optimierung (Retrospektive 2026-09-07): agents/agent_trainer_agent.py wird angewiesen,
# bei statisch erkennbaren Fehlermustern (z.B. "Paket X fehlt in requirements.txt") zusätzlich
# zur Prompt-Regel einen "**Deterministischer Check-Vorschlag:** ..." zu formulieren, WEIL eine
# Prompt-Regel für solche Muster nachweislich unzuverlässig ist (siehe dortiger Docstring). Bis
# hierhin wurde dieser Vorschlag aber nirgends aufgefangen - nur die Lern-Regeln (```json
# "learnings"-Block, siehe _extract_and_store_learnings() unten) wurden persistiert, der
# Prosa-Vorschlag stand nur einmalig im Trainer-Bericht dieses einen Laufs und ging danach
# spurlos verloren. Genau DAS war die Lücke, die core/pre_flight_check.py/core/verifier/
# completeness.py erst nach einer vollständigen manuellen Analysesitzung (statt automatisch aus
# dem Trainer-Report heraus) um die greenlet-/python-multipart-/TrustedHostMiddleware-Checks
# ergänzte. _DETERMINISTIC_CHECK_SUGGESTION_RE fängt diese Zeile jetzt ab (beide im Prompt
# vorkommenden Varianten: "...Vorschlag:**" direkt gefolgt vom Text, und "...Vorschlag**
# (Klammerzusatz):" mit dem Text danach oder in der Folgezeile).
_DETERMINISTIC_CHECK_SUGGESTION_RE = re.compile(
    r"Deterministischer\s+Check-Vorschlag\**[^:\n]*:\s*(.*)"
)
# Der Beispiel-/Platzhaltertext aus dem System-Prompt selbst ("leer lassen, wenn...") - taucht
# auf, wenn das Modell die Formatvorlage unverändert übernimmt statt sie auszufüllen oder bewusst
# leer zu lassen; ein solcher Treffer ist kein echter Vorschlag und wird verworfen.
_CHECK_SUGGESTION_PLACEHOLDER_RE = re.compile(r"leer lassen|z\.\s?B\.\s*\"", re.IGNORECASE)


class RetrospectiveMixin:
    """Erstellt Retrospektiven und speist die persistente Agenten-Wissensbasis."""

    async def _run_retrospective(
        self,
        user_request: str,
        results: list[AgentResult],
        total_duration: float,
    ) -> AgentResult | None:
        """
        P2-4 (ROADMAP_TEMP.md, "Variante B"): rein deterministische Kennzahlen-Zusammenfassung,
        KEIN LLM-Aufruf mehr. Realer Fund (Lauf `cachegrid_proxy`): der bisherige LLM-Retrospektiv-
        Schritt bekam nur einen auf ~250 Zeichen je Agent gekürzten Prosa-Auszug ohne
        `project_dir`/Werkzeuge - 1.325 Prompt-Tokens für eine Analyse, die auf derselben
        unvollständigen Evidenz wie core/root_cause_analyst.py aufsetzte (der ECHTE Werkzeug-
        Zugriff hat), aber zusätzlich Tokens kostete und bei widersprüchlicher Bewertung
        (zwei LLM-Analysen desselben Laufs mit unterschiedlicher Evidenztiefe) verwirrende,
        sich widersprechende Lektionen erzeugen konnte. Die LLM-Tiefenanalyse bleibt jetzt
        ausschließlich beim root_cause_analyst (siehe _maybe_run_root_cause_analysis), der
        echten Dateizugriff hat - dieser Schritt liefert nur die harten Zahlen, aus denen
        _run_agent_trainer_self_optimization() weiterhin fehlerhafte/teure Agenten herausfiltert.
        """
        if "retrospective" not in self._agents:
            return None

        erfolgreich = sum(1 for r in results if r.success)
        gesamt_tokens = sum(r.total_tokens for r in results)
        lines = [
            "## Automatische Kennzahlen-Retrospektive (deterministisch, kein LLM-Aufruf)",
            f"- Dauer gesamt: {total_duration:.1f}s | Agenten-Aufrufe: {len(results)} "
            f"({erfolgreich}/{len(results)} erfolgreich) | Tokens gesamt: {gesamt_tokens}",
        ]
        for r in results:
            if not r.success:
                lines.append(f"- ❌ {r.agent_name} ({r.agent_id}): {r.error}")
        top_tokens = sorted(results, key=lambda r: r.total_tokens, reverse=True)[:3]
        if top_tokens:
            lines.append(
                "- Token-intensivste Agenten: "
                + ", ".join(f"{r.agent_id} ({r.total_tokens})" for r in top_tokens)
            )

        return AgentResult(
            task_id="retro_task",
            agent_id="retrospective",
            agent_name="Retrospektive & Lessons Learned Agent",
            success=True,
            content="\n".join(lines),
        )

    async def _run_agent_trainer_self_optimization(
        self,
        user_request: str,
        results: list[AgentResult],
        retro_content: str,
        verification_ok: bool = True,
        verification_summary: str = "",
        definition_of_done=None,
    ) -> AgentResult | None:
        trainer = self._agents.get("agent_trainer")

        # Infrastruktur-Ausfälle (Kontingent erschöpft) sind kein Lernsignal für Prompts.
        has_errors = any(not r.success and r.failure_class != FAILURE_CLASS_PROVIDER_EXHAUSTED for r in results)
        # Früher `> 4000`: jeder Agent liegt real bei 10k-60k Tokens, der Trainer lief dadurch nach
        # JEDEM Lauf (120k-146k Tokens, ~15 % des Laufs). Jetzt nur echte Ausreißer.
        high_usage = any(r.total_tokens > TRAINER_HIGH_USAGE_TOKENS_PER_CALL for r in results)

        # Realer Fund (pulseflow_gateway, 20260911_095217): der Lauf schloss mit
        # verification_ok=true ab, obwohl KEIN einziger Agent auch nur eine Datei geschrieben
        # hatte - core/definition_of_done.py blockiert das inzwischen über die Kriterien
        # "files_written"/"missing_entrypoint" (harte, gegen das Dateisystem geprüfte Fakten,
        # anders als eine Heuristik über die hier übergebene `results`-Liste, die z.B. bei
        # Review-Only-Agenten oder einem nur TEILWEISEN Ergebnis-Ausschnitt legitim leere
        # files_written trägt, ohne dass das einen Schein-Erfolg bedeutet). Ohne diesen Zweig
        # hätte has_errors=False (kein Agent meldete selbst einen Fehler), high_usage evtl.
        # False, verification_ok=True die Bedingung unten den Trainer-Aufruf komplett
        # übersprungen und der Lauf wäre NIE als Negativ-Erkenntnis gespeichert worden. Genau
        # DIESE beiden DoD-Kriterien blockierend zu sehen ist der Extremfall eines Schein-
        # Erfolgs und erzwingt deshalb IMMER eine Analyse, unabhängig von has_errors/high_usage/
        # verification_ok.
        false_success = definition_of_done is not None and any(
            c.key in ("files_written", "missing_entrypoint") for c in definition_of_done.blocking_criteria
        )

        if not has_errors and not high_usage and verification_ok and not false_success:
            return None

        # Deterministische Buchführung (KEIN LLM-Aufruf, kann daher nie an einem erschöpften
        # Provider oder einem trainer_result.success=False scheitern): ein Schein-Erfolg ist DAS
        # lehrreichste, teuerste Signal, das dieses Team produzieren kann - es landet deshalb
        # IMMER in memory/team_lessons.jsonl, auch wenn der LLM-Trainer weiter unten selbst
        # ausfällt oder kein gültiges JSON liefert.
        if false_success:
            blocker_detail = ", ".join(c.key for c in definition_of_done.blocking_criteria)
            record_lesson(
                project_slug=getattr(self, "last_project_slug", "project"),
                category="false_success_no_source_files",
                detail=(
                    f"Lauf schloss mit verification_ok={verification_ok} ab, obwohl keine "
                    f"Quelldatei geschrieben wurde (Blocker: {blocker_detail}). Auftrag: "
                    f"{user_request[:300]}"
                ),
            )

        if not trainer:
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
        if false_success:
            context += (
                "\nKRITISCHER SCHEIN-ERFOLG: Der Lauf galt als grün/verifiziert, obwohl KEINE "
                "einzige Quelldatei geschrieben wurde (Definition of Done, Blocker: "
                f"{blocker_detail}). Analysiere, welcher Code-schreibende Agent (backend/"
                "frontend/database/devops) seine Aufgabe ohne write_file/edit_file abgeschlossen "
                "hat, und formuliere eine Regel, die genau das für diesen Agenten zukünftig verbietet.\n"
            )

        task = AgentTask(
            task_id="trainer_auto_opt",
            agent_id="agent_trainer",
            description="Analysiere die aufgetretenen Fehler/Ineffizienzen und liefere konkrete Prompt-Schärfungen zur Selbstoptimierung der Agenten.",
            context=context,
            max_tool_iterations=TRAINER_MAX_TOOL_ITERATIONS,
        )
        trainer_result = await self._execute_and_log(trainer, task)

        if trainer_result and trainer_result.success and trainer_result.content:
            self._extract_and_store_learnings(trainer_result.content)
            self._extract_and_store_check_suggestions(trainer_result.content)

        return trainer_result

    async def _maybe_run_root_cause_analysis(
        self,
        user_request: str,
        verification_ok: bool,
        verification_summary: str,
        files_written: int,
        project_dir: str,
        notify: Callable[[str], None],
    ) -> None:
        """Gesamtsystem-Analyse 2026-09-14, Punkt 3.1 "Automatisierter Root-Cause-Analyst": der
        obige Trainer-Aufruf (_run_agent_trainer_self_optimization) läuft zwar automatisch nach
        JEDEM Lauf, aber OHNE project_dir/allow_tools an seiner AgentTask - er bekommt nur einen
        gekürzten Prosa-Auszug, nie echten Zugriff auf die rohen Logs oder den tatsächlichen
        Code. Genau DIESE Lücke schließt core/root_cause_analyst.py: bei einem echten
        Warnsignal (should_trigger()) bekommt ein eigener, zusätzlicher Aufruf des
        agent_trainer-Agenten read-only Werkzeugzugriff auf das GESAMTE Repository
        (project_dir=BASE_DIR - sowohl den generierten Projekt-Code als auch den Framework-Code
        selbst, siehe dortiger Docstring) und die vollen (gedeckelten) Rohdaten des Laufs.

        Best-effort und komplett additiv wie core/roadmap_advisor.py/core/optimization_
        advisor.py: ein Fehler hier darf einen sonst erfolgreichen Lauf NIE nachträglich
        kippen, und ENABLE_ROOT_CAUSE_ANALYST (config.py, standardmäßig AN, da rein
        vorschlagend - siehe dortiger Docstring) erlaubt ein Abschalten ohne Codeänderung."""
        import config
        from core.root_cause_analyst import run_analysis, should_trigger

        if not config.ENABLE_ROOT_CAUSE_ANALYST:
            return

        trigger = should_trigger(
            verification_ok=verification_ok,
            files_written=files_written,
            recurring_signature_seen_before=has_repeated_failure(project_dir),
        )
        if not trigger.should_run:
            return

        run_logger = getattr(self, "_run_logger", None)
        notify(f"  🔬 [bold cyan]Root-Cause-Analyse[/bold cyan] wird ausgelöst ({trigger.reason})...")
        try:
            report = await run_analysis(
                self,
                project_slug=getattr(self, "last_project_slug", "") or "project",
                user_request=user_request,
                verification_summary=verification_summary,
                run_log_path=getattr(run_logger, "run_log_path", None),
                verification_log_path=getattr(run_logger, "verification_log_path", None),
                project_trace_path=getattr(run_logger, "project_trace_path", None),
            )
        except Exception as e:
            notify(f"  ⚠️ [dim yellow]Root-Cause-Analyse fehlgeschlagen: {e}[/dim yellow]")
            return

        if report.ok:
            notify(
                f"  🔬 [bold green]Root-Cause-Analyse abgeschlossen:[/bold green] "
                f"{len(report.findings)} Befund(e) als Ticket(s) festgehalten: {', '.join(report.ticket_ids)}"
            )
        else:
            notify(f"  ⚠️ [dim yellow]Root-Cause-Analyse ohne verwertbaren Befund: {report.error}[/dim yellow]")

    @staticmethod
    def _maybe_harvest_reusable_components(
        verification_ok: bool, project_dir: str, project_slug: str, notify: Callable[[str], None],
    ) -> None:
        """Gesamtsystem-Analyse 2026-09-14, Punkt 3.2: übernimmt wiederkehrende Infrastruktur-
        Bausteine (Circuit Breaker, Rate-Limiter, ...) aus einem ERFOLGREICH VERIFIZIERTEN
        Projekt in die projektübergreifende Bibliothek (core/component_library.py), damit
        künftige Projekte sie über das search_component_library-Werkzeug wiederverwenden können,
        statt dieselben Bausteine (und dieselben Bugklassen darin) immer wieder neu zu
        erfinden. Bewusst NUR bei verification_ok=True: core/component_library.py.harvest_
        from_project()/_is_stub() filtert zwar bereits offensichtliche Stubs heraus, aber
        "verifiziert" bleibt die stärkste verfügbare Qualitätsschranke - ein Baustein aus einem
        gescheiterten Lauf soll nicht in die Bibliothek gelangen, selbst wenn er zufällig lang
        genug aussieht. Rein additiv/best-effort wie jeder andere Post-Run-Schritt hier."""
        if not verification_ok:
            return
        try:
            from core.component_library import harvest_from_project

            added = harvest_from_project(project_dir, project_slug)
            if added:
                notify(f"  📦 [dim cyan]{len(added)} wiederverwendbare Baustein(e) in die Komponenten-Bibliothek übernommen.[/dim cyan]")
        except Exception as e:
            notify(f"  ⚠️ [dim yellow]Komponenten-Bibliothek konnte nicht aktualisiert werden: {e}[/dim yellow]")

    @staticmethod
    def _extract_and_store_check_suggestions(report_text: str) -> None:
        """Fängt "**Deterministischer Check-Vorschlag:** ..."-Zeilen aus dem Trainer-Report ab
        (siehe _DETERMINISTIC_CHECK_SUGGESTION_RE-Docstring oben) und persistiert sie über
        core/team_memory.py.record_lesson() unter dem Team-weiten Pseudo-Projekt "_team" - dem
        bereits etablierten Muster für reine Team-Selbstoptimierungs-Buchführung (siehe dortiges
        unused_agent). Landet damit dauerhaft in memory/team_lessons.jsonl, wo ein Mensch (oder
        eine spätere KI-Team-Analysesitzung) es beim nächsten Blick auf die Team-Lektionen sieht,
        statt dass der Vorschlag nur im Transkript dieses einen Laufs verschwindet. Kategorie
        "deterministic_check_suggestion" ist bewusst in _LOW_SEVERITY_CATEGORIES eingestuft
        (siehe dort) - ein Vorschlag ist eine Handlungsempfehlung an das Framework-Team, kein
        akuter Governance-Blocker eines laufenden Projekts, und soll dessen knappe Prompt-Plätze
        nicht verdrängen."""
        for match in _DETERMINISTIC_CHECK_SUGGESTION_RE.finditer(report_text):
            suggestion = match.group(1).strip(" `\"'*")
            if len(suggestion) <= 15 or _CHECK_SUGGESTION_PLACEHOLDER_RE.search(suggestion):
                continue
            record_lesson("_team", "deterministic_check_suggestion", suggestion)

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
