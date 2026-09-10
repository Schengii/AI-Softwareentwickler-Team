"""
agents/orchestrator/reporting.py – ReportingMixin: deterministische (kein LLM-Aufruf)
Berichts-/Statusbausteine – Live-Statuszeilen, Datei-Owner-Tracking, Kollisions-Erkennung,
Rückfrage-/Kollisions-Abschnitte im Abschlussbericht, die tatsächlich geschriebenen Dateien
(direkt von der Platte gelesen) sowie die abschließende Kennzahlen-/Ressourcentabelle.
"""

from pathlib import Path

from agents.base_agent import CODE_WRITING_AGENT_IDS
from config import MAX_RUN_TOKENS, ORCHESTRATOR_MODEL
from core.message_bus import AgentResult


class ReportingMixin:
    """Deterministische Berichts-/Statusbausteine (kein LLM-Aufruf)."""

    @staticmethod
    def _status_notify_line(icon_success: str, icon_failure: str, agent_name: str, duration: float, success: bool, error: str | None) -> str:
        """
        Baut die Live-Statuszeile für einen abgeschlossenen Agenten-Aufruf. Realer Fund aus
        einem echten Lauf: Bei einem Fehlschlag zeigte diese Zeile bisher NUR "❌ Fehler:
        <Agent> (61.7s)" ohne jeden Hinweis auf die Ursache – der reale Fehlertext (AgentResult.error)
        landete nirgends beim Nutzer, weder live noch im Endergebnis, nur (verkürzt/paraphrasiert)
        in der von einem LLM verfassten Retrospektive. Jetzt wird der rohe Fehlertext direkt mitgeliefert.
        """
        icon = icon_success if success else icon_failure
        error_note = f" — {error[:200]}" if not success and error else ""
        return f"  {icon}: {agent_name} ({duration:.1f}s){error_note}"

    @staticmethod
    def _first_line(text: str, max_chars: int = 160) -> str:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return (first[:max_chars] + "…") if len(first) > max_chars else first

    @staticmethod
    def _update_file_owners(file_owners: dict[str, str], results: list[AgentResult]) -> None:
        """Merkt sich, welcher Agent welche Datei tatsächlich geschrieben hat (für die Verifikationsschleife)."""
        for res in results:
            for rel_path in res.files_written:
                file_owners[rel_path] = res.agent_id

    @staticmethod
    def _infer_owner_from_path(file_path: str) -> str | None:
        """
        Fallback-Owner-Ermittlung für Vollständigkeits-Funde, wenn `file_owners` keinen
        Eintrag für den Pfad hat - realer Fund: eine bereits VOR dem aktuellen Lauf
        existierende Datei (z.B. `frontend/package.json`, vom Frontend-Agenten in einem
        früheren Durchlauf geschrieben) taucht in `file_owners` nicht auf, weil dieses Dict
        nur Schreibvorgänge des AKTUELLEN Laufs erfasst (siehe `_update_file_owners`). Ohne
        diesen Fallback bricht die Vollständigkeits-Fixschleife dann mit "keinem Agenten
        eindeutig zuordenbar" ab, obwohl der zuständige Spezialist anhand des Pfads klar
        erkennbar ist. Reine Pfad-/Namens-Heuristik, kein Dateiinhalt nötig.
        """
        lowered = file_path.replace("\\", "/").lower()
        if (
            "frontend/" in lowered
            or lowered.endswith((".tsx", ".jsx", ".vue", ".html", ".css"))
            or "package.json" in lowered
        ):
            return "frontend"
        if "test_" in lowered or "tests/" in lowered:
            return "tester"
        if lowered.endswith(".py") or "app/" in lowered or "src/" in lowered:
            return "backend"
        if "readme" in lowered:
            return "readme"
        return None

    @staticmethod
    def _detect_file_write_collisions(member_results: list[AgentResult]) -> dict[str, list[str]]:
        """
        Erkennt, ob innerhalb EINES parallelen Ausführungs-Batches (mehrere Fachteam-
        Mitglieder gleichzeitig per asyncio.gather, siehe _run_agents_parallel) mehr als ein
        Agent dieselbe Datei geschrieben hat. Nur für parallele Batches relevant: bei
        sequenzieller Ausführung sieht ein späterer Agent den Stand des früheren bereits auf
        der Platte, ein Überschreiben dort ist eine informierte Entscheidung, keine blinde
        Kollision. Gibt {rel_path: [agent_id, ...]} nur für tatsächlich betroffene Pfade
        zurück (mind. 2 unterschiedliche Schreiber), in stabiler Reihenfolge nach erstem
        Auftreten.
        """
        writers: dict[str, list[str]] = {}
        for res in member_results:
            for rel_path in res.files_written:
                agents = writers.setdefault(rel_path, [])
                if res.agent_id not in agents:
                    agents.append(res.agent_id)
        return {path: agents for path, agents in writers.items() if len(agents) > 1}

    @staticmethod
    def _build_clarification_section(results: list[AgentResult]) -> str:
        """
        Deterministischer Abschnitt (kein LLM-Aufruf) mit allen über `ask_human_for_clarification`
        (core/agent_toolbox.py) aufgezeichneten Rückfragen dieses Laufs - siehe
        self.last_needs_human_input/self.last_clarification_questions in process() weiter
        unten. Leer, wenn keine Rolle eine echte Blockade gemeldet hat.
        """
        entries = [(r, q) for r in results for q in r.clarification_questions]
        if not entries:
            return ""
        lines = [
            "### ❓ Offene Rückfragen (mitten in der Aufgabe aufgetreten)",
            "Mindestens eine Fachrolle ist auf eine echte, für die Aufgabe entscheidende "
            "Unklarheit gestoßen und hat NICHT geraten – bitte beantworten, bevor das Ergebnis "
            "unverändert übernommen wird:",
        ]
        for r, q in entries:
            lines.append(f"- **{r.agent_name}**: {q}")
        return "\n".join(lines)

    @staticmethod
    def _build_file_collision_section(collisions: list[dict]) -> str:
        """Deterministischer Abschnitt im Abschlussbericht (kein LLM-Aufruf) – siehe collision_sink."""
        if not collisions:
            return ""
        lines = [
            "### ⚠️ Datei-Kollisionen bei paralleler Fachteam-Arbeit",
            "Mehrere gleichzeitig arbeitende Fachteam-Mitglieder haben dieselbe Datei "
            "geschrieben – die jeweils zuerst geschriebene Version könnte überschrieben "
            "worden sein. Bitte die betroffene(n) Datei(en) vor der Weiterverwendung prüfen:",
        ]
        for entry in collisions:
            lines.append(f"- `{entry['path']}` in {entry['phase']}: {', '.join(entry['agents'])}")
        return "\n".join(lines)

    def _format_results_for_review(self, results: list[AgentResult]) -> str:
        """
        Realer Fund (echte Rückfrage eines governance_lead-Konsolidierungslaufs): schlugen
        ALLE Mitglieder einer Phase fehl oder lieferten leeren Inhalt (z.B. ein reines
        Review-Tool-Ergebnis ohne abschließenden Text), war `results_text` in
        _run_department_consolidation() komplett LEER - der Teamleiter bekam wörtlich
        "Deine Fachteam-Mitglieder haben folgende Ergebnisse geliefert:\n\n\nPrüfe sie..."
        und stellte folgerichtig eine Rückfrage ("Ergebnisse wurden im Prompt nicht
        mitgeliefert"), statt einen Bericht zu schreiben. Fehlgeschlagene Mitglieder werden
        jetzt IMMER aufgeführt (mit Fehlertext statt Inhalt), damit der Teamleiter wenigstens
        weiß, WARUM nichts zu prüfen ist, statt vor einem leeren Block zu stehen.
        """
        blocks = []
        for r in results:
            if r.success and r.content:
                files_note = f" (Dateien: {', '.join(r.files_written)})" if r.files_written else ""
                blocks.append(f"### Ergebnis von {r.agent_name}{files_note}:\n{r.content[:2000]}")
            elif not r.success:
                blocks.append(f"### ❌ {r.agent_name} ist fehlgeschlagen:\n{(r.error or 'Kein Fehlertext protokolliert.')[:500]}")
            else:
                # success=True, aber content leer - z.B. ein reiner Tool-Aufruf (list_files/
                # read_file) ohne abschließende Textantwort. Auch das sichtbar machen statt
                # stillschweigend zu verschwinden, aus demselben Grund wie oben.
                files_note = f" (Dateien: {', '.join(r.files_written)})" if r.files_written else ""
                blocks.append(f"### ⚠️ {r.agent_name} lieferte keinen Text-Inhalt{files_note} (nur Werkzeug-Aufrufe, keine abschließende Textantwort).")
        return "\n\n".join(blocks)

    # Caps analog zu ResultAggregator.MAX_CONTENT_CHARS_PER_RESULT - verhindert, dass ein
    # Projekt mit vielen/großen Dateien die finale Antwort unbegrenzt aufbläht. Vollständiger
    # Inhalt liegt immer im Workspace-Verzeichnis, unabhängig von dieser Kürzung.
    MAX_CHARS_PER_REAL_FILE = 3000
    MAX_TOTAL_REAL_FILES_CHARS = 20000
    _LANG_BY_EXTENSION = {
        ".py": "python", ".js": "javascript", ".jsx": "jsx", ".ts": "typescript",
        ".tsx": "tsx", ".json": "json", ".md": "markdown", ".html": "html",
        ".css": "css", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
        ".sh": "bash", ".sql": "sql", ".txt": "",
    }

    def _build_real_files_section(self, project_dir: str, file_owners: dict[str, str]) -> str:
        """
        Liest die TATSÄCHLICH geschriebenen Dateien direkt von der Platte (kein LLM-Aufruf,
        daher immer exakt korrekt) – Gegenstück zur LLM-Synthese oben, die Code nur
        beschreiben, nicht mehr reproduzieren soll (siehe SYNTHESIZE_SYSTEM_PROMPT). Leer,
        wenn keine Dateien geschrieben wurden (z.B. ein reiner Planungs-/Analyse-Lauf).
        """
        if not file_owners:
            return ""

        blocks = ["### 📁 Tatsächlich geschriebene Dateien (direkt von der Platte gelesen, nicht vom LLM reproduziert)"]
        total_chars = 0
        for rel_path in sorted(file_owners):
            if total_chars >= self.MAX_TOTAL_REAL_FILES_CHARS:
                blocks.append(f"\n… weitere Dateien gekürzt (Gesamtlänge begrenzt) – vollständig im Workspace unter `{project_dir}`.")
                break
            try:
                content = (Path(project_dir) / rel_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # z.B. Binärdatei oder zwischenzeitlich gelöscht - kein Fehler, einfach übersprungen
            truncated = content[: self.MAX_CHARS_PER_REAL_FILE]
            note = "" if len(content) <= self.MAX_CHARS_PER_REAL_FILE else "\n… [gekürzt, vollständiger Inhalt im Workspace] …"
            lang = self._LANG_BY_EXTENSION.get(Path(rel_path).suffix, "")
            blocks.append(f"\n**`{rel_path}`**\n```{lang}\n{truncated}{note}\n```")
            total_chars += len(truncated)

        return "\n".join(blocks)

    def _build_metrics_summary(
        self,
        results: list[AgentResult],
        synth_tokens: int,
        total_duration: float,
        project_dir: str,
        run_start_tokens: int | None = None,
        text_fallback_paths: list[str] | None = None,
    ) -> str:
        total_prompt_tokens = sum(r.prompt_tokens for r in results)
        total_completion_tokens = sum(r.completion_tokens for r in results) + synth_tokens
        grand_total_tokens = sum(r.total_tokens for r in results) + synth_tokens
        total_tool_calls = sum(r.tool_calls_count for r in results)
        total_files_written = len({f for r in results for f in r.files_written})

        lines = [
            "### 📈 Projekt-Kennzahlen & Ressourcen-Verbrauch\n",
            f"- ⏱️ **Gesamtdauer:** `{total_duration:.2f} Sekunden`",
            f"- 🪙 **Gesamtverbrauch Tokens:** `{grand_total_tokens:,}` (Prompt: `{total_prompt_tokens:,}` | Completion: `{total_completion_tokens:,}`)",
        ]

        # Nur anzeigen, wenn ein hartes Lauf-Budget konfiguriert ist (config.MAX_RUN_TOKENS) –
        # nutzt den GLOBALEN Token-Guard-Zähler (inkl. aller Fallback-Hops), nicht nur die Summe
        # der einzelnen AgentResult.total_tokens, da diese Fehlschläge vor Ergebnis nicht erfasst.
        if MAX_RUN_TOKENS > 0 and run_start_tokens is not None:
            used = self._tokens_used_since(run_start_tokens)
            pct = min(100, round(used / MAX_RUN_TOKENS * 100))
            budget_icon = "🚨" if used >= MAX_RUN_TOKENS else "🪙"
            lines.append(f"- {budget_icon} **Lauf-Budget:** `{used:,} / {MAX_RUN_TOKENS:,}` Tokens (`{pct}%`)")
        if self._project_token_budget > 0 and run_start_tokens is not None:
            # Kumuliert über ALLE bisherigen Läufe an diesem Projekt (nicht nur diesen einen
            # Lauf, siehe _project_budget_exceeded) - eigene Zeile statt in die Lauf-Budget-
            # Zeile oben gemischt, da beide Budgets unabhängig konfiguriert/erschöpft sein können.
            project_used = self._project_tokens_before_run + self._tokens_used_since(run_start_tokens)
            project_pct = min(100, round(project_used / self._project_token_budget * 100))
            project_icon = "🚨" if project_used >= self._project_token_budget else "🪙"
            lines.append(
                f"- {project_icon} **Projekt-Budget** (`/constitution`, über alle Läufe): "
                f"`{project_used:,} / {self._project_token_budget:,}` Tokens (`{project_pct}%`)"
            )

        lines += [
            f"- 🛠️ **Werkzeug-Aufrufe (echte Datei-/Testoperationen):** `{total_tool_calls:,}` | **Dateien geschrieben/geändert:** `{total_files_written}`",
            f"- 📁 **Projektverzeichnis:** `{project_dir}`\n",
            "| KI-Agent | Rolle / Fachbereich | Modell | Dauer | Tokens | Tool-Calls | Status |",
            "|---|---|---|---|---|---|---|",
        ]

        for r in results:
            status_icon = "✅" if r.success else "❌"
            lines.append(
                f"| **{r.agent_name}** | `{r.agent_id}` | `{r.model_used or 'default'}` | {r.duration_seconds:.1f}s | {r.total_tokens:,} | {r.tool_calls_count} | {status_icon} |"
            )

        lines.append(
            f"| **Hauptagent (Synthese)** | `orchestrator` | `{ORCHESTRATOR_MODEL}` | - | {synth_tokens:,} | - | ✅ |"
        )

        # Kritische Rollen, die unterhalb ihrer konfigurierten Modellstufe liefen, sichtbar machen
        # (core/model_capability.py) - eine Abstufung darf nie nur in der Modell-Spalte versteckt sein.
        from core.model_capability import describe_degraded_results

        degraded = describe_degraded_results(results)
        if degraded:
            lines.append("\n### ⚠️ Modell-Abstufung bei kritischen Rollen\n")
            lines += [f"- {line}" for line in degraded]

        # Rohe Fehlertexte GARANTIERT sichtbar machen – nicht nur (verkürzt/paraphrasiert) über
        # die Retrospektive, die als eigener LLM-Aufruf den Fehler frei zusammenfasst und dabei
        # auch ungenau werden kann. Realer Fund: Ohne dies verschwand die einzige Fehlerursache
        # eines gescheiterten Laufs komplett aus dem Nutzer-sichtbaren Ergebnis.
        failed = [r for r in results if not r.success and r.error]
        if failed:
            lines.append("\n### ❌ Rohe Fehlermeldungen (ungefiltert, nicht vom LLM zusammengefasst)\n")
            for r in failed:
                lines.append(f"- **{r.agent_name}** (`{r.agent_id}`): `{r.error[:500]}`")

        # "Erfolgreich", aber real NICHTS im Projekt verändert: eine Rolle mit eindeutigem
        # Artefakt-Auftrag (CODE_WRITING_AGENT_IDS) hat Werkzeuge genutzt (tool_calls_count > 0,
        # war also im agentischen Loop) und trotzdem 0 Dateien geschrieben – der komplette
        # Tokenverbrauch dieses Agenten ging vermutlich in reinen Antworttext statt in echte
        # write_file/edit_file-Aufrufe. Siehe CODE_WRITING_AGENT_IDS oben für den realen Fund.
        silent_no_write = [
            r for r in results
            if r.success and r.agent_id in CODE_WRITING_AGENT_IDS and r.tool_calls_count > 0 and not r.files_written
        ]
        if silent_no_write:
            lines.append(
                "\n### ⚠️ Erfolg gemeldet, aber keine Datei geschrieben (vermutlich verpuffter Tokenverbrauch)\n"
            )
            for r in silent_no_write:
                lines.append(
                    f"- **{r.agent_name}** (`{r.agent_id}`): {r.tool_calls_count} Werkzeug-Aufruf(e), "
                    f"{r.total_tokens:,} Tokens, aber 0 Dateien geschrieben. Prüfe `content` dieses "
                    "Agenten manuell – der Code steckt wahrscheinlich nur im Antworttext."
                )

        # Realer Fund: per Regex aus freiem Antworttext geparste Dateien (siehe process(),
        # AUTO_SAVE_WORKSPACE-Block) sind fehleranfälliger als ein natives write_file-Tool-
        # Argument - ein beobachteter Fall lieferte nur einen Patch-/Integrations-Ausschnitt
        # statt einer vollständigen Datei (fehlende Imports, Bezug auf nicht definierte Namen).
        # core/verifier.py.check_lint() findet solche Fälle zuverlässig (z.B. F821 undefined
        # name), aber die Zuordnung "welche der vielen Lint-Fehler stammt von einer Text-
        # Fallback-Datei" war bisher nicht möglich - diese Liste macht die betroffenen Pfade
        # NAMENTLICH sichtbar, statt nur als anonyme Zahl im Live-Log.
        if text_fallback_paths:
            lines.append(
                "\n### 📝 Per Text-Fallback gespeicherte Dateien (nicht über das reguläre "
                "Werkzeug interface geschrieben)\n"
            )
            lines.append(
                "Diese Dateien wurden aus dem freien Antworttext eines Agenten per Regex "
                "extrahiert, nicht über einen echten `write_file`/`edit_file`-Aufruf – prüfe sie "
                "bei einem Lint-/Testfehler zuerst, da sie öfter unvollständig sind (z.B. nur ein "
                "Patch-Ausschnitt statt einer vollständigen Datei):\n"
            )
            for path in text_fallback_paths:
                lines.append(f"- `{path}`")

        return "\n".join(lines)
