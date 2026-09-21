"""
interface/cli/git_release.py - GitHub-Push-Gate, Release/Rollback/Branch-Protection, Worktrees.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLIGitReleaseMixin buendelt
alle Aktionen, die den echten Git-/GitHub-Zustand veraendern (Commit, Push, PR, Release,
Rollback, Branch-Protection) - jede davon zeigt vorab eine Vorschau und fragt bestaetigen.

`notify_external` wird in `_report_ci_status` bewusst PER-AUFRUF ueber `interface.cli`
re-importiert statt am Modulkopf - bestehende Tests patchen ihn als `interface.cli.notify_external`
(siehe Modul-Docstring von scripts/_assemble_cli.py).
"""

import asyncio
import uuid

from rich.panel import Panel
from rich.prompt import Confirm

from config import BRANCH_PROTECTION_REQUIRED_REVIEWS, ENABLE_PR_WORKFLOW, GIT_PROTECTED_BRANCHES
from core import framework_release
from core.backlog_store import new_ticket_id, upsert_ticket
from interface.cli._shared import console


class CLIGitReleaseMixin:
    async def _ask_for_git_push(self, task_summary: str, ticket_id: str | None = None) -> None:
        """
        Fragt den Nutzer, ob der GitHub-Agent Änderungen committen und pushen soll.

        Zeigt VOR der Bestätigung die konkret betroffenen Dateien, den Diff-Umfang und die
        exakte Commit-Message – nicht nur ein blindes Ja/Nein. Das ist wichtig, weil
        github_agent.commit() intern `git add -A` ausführt und damit den GESAMTEN
        Repo-Stand staged, nicht nur die Dateien des gerade bearbeiteten Projekts – der
        Nutzer soll das vor einer irreversiblen Aktion (Push) wirklich sehen können.

        `ticket_id`: das im gemeinsamen Backlog (core/backlog_store.py) bereits als
        "in_progress" angelegte Ticket dieses Laufs (siehe _process_task()) – wird hier auf
        den tatsächlichen Ausgang finalisiert (review/done/blocked). Ohne Angabe (der
        manuelle `/push`-Befehl hat keinen vorherigen Lauf-Ticket) wird eins neu angelegt.
        """
        ticket_id = ticket_id or new_ticket_id("cli")

        github_agent = self._orchestrator._agents.get("github")
        if not github_agent:
            return

        diff_status = github_agent.get_status()
        if not diff_status:
            # Nichts zu committen - aus Sicht des Backlogs ist die Arbeit trotzdem
            # abgeschlossen (kein Push-Schritt für diese Aufgabe nötig).
            upsert_ticket(ticket_id=ticket_id, title=task_summary[:80], source="cli", status="done")
            return

        changed_files = [line.strip() for line in diff_status.splitlines() if line.strip()]
        diff_stat = github_agent.get_diff()

        # Realer Fund: commit()/push() prüften den Inhalt nie – ein Agent, der versehentlich
        # einen echten API-Key/ein Passwort in eine generierte Datei schreibt, hätte diesen
        # Secret unbemerkt auf GitHub gepusht. scan_for_secrets() staged (git add -A, dasselbe
        # tut commit() ohnehin gleich danach) und durchsucht den vollen Diff regelbasiert
        # (core/secret_scanner.py) – rein lesend, blockiert hier noch nichts selbst.
        secret_findings = github_agent.scan_for_secrets()
        secret_note = ""
        if secret_findings:
            finding_lines = "\n".join(
                f"  {f.file_path}:{f.line_number} [{f.rule}] {f.snippet}"
                for f in secret_findings[:10]
            )
            if len(secret_findings) > 10:
                finding_lines += f"\n  … und {len(secret_findings) - 10} weitere Funde"
            secret_note = (
                f"\n\n[bold red]🔑 Möglicher Secret-Fund ({len(secret_findings)}):[/bold red]\n"
                f"{finding_lines}\n"
                "[dim]Vor dem Pushen prüfen – ein erfolgter Push entfernt diese Werte NICHT "
                "mehr rückwirkend aus der Historie.[/dim]"
            )

        if self._looks_like_raw_user_request(task_summary):
            # task_summary ist erkennbar keine Zusammenfassung, sondern die an das Team
            # gerichtete Anfrage selbst – der (immer kurze, bereits sanitierte) Projektordner-
            # name ist hier ein zuverlässigerer Commit-Betreff als ein weiteres hartes [:50].
            fallback_slug = getattr(self._orchestrator, "last_project_slug", "") or "projekt"
            commit_msg = f"feat: {fallback_slug} weiterentwickelt via AI Developer Team"
        else:
            commit_msg = f"feat: implement {self._truncate_at_word(task_summary, 50)} via AI Developer Team"

        # PR-Workflow statt Direct-Push: Ein echtes Team committet nicht direkt auf den
        # Hauptbranch. AKTIV, wenn der aktuelle Branch tatsächlich ein Hauptbranch ist ODER
        # noch ein "feat/"-Branch aus einem VORHERIGEN PR-Workflow-Lauf ist (das
        # Arbeitsverzeichnis wechselt nach einem Lauf bewusst NICHT mehr zurück, siehe unten
        # - ein "feat/"-Branch ist damit fast immer unser eigener Leftover-Zustand, kein
        # bewusst vom Menschen ausgecheckter Feature-Branch, den es zu respektieren gälte).
        # Schon auf einem ANDEREN, nicht-protected Branch (z.B. ein isolierter
        # Selbstverbesserungs-Worktree mit "ai-team/"-Präfix, oder ein manuell vom Menschen
        # ausgecheckter Branch) -> ganz normal direkt darauf committen/pushen. Zusätzlich muss
        # die `gh`-CLI installiert + eingeloggt sein (gh_ready()) - sonst Graceful Degradation
        # auf den bisherigen Direct-Push, statt den Nutzer ganz zu blockieren.
        original_branch = github_agent.get_current_branch()
        is_leftover_feature_branch = original_branch.startswith("feat/") and original_branch not in GIT_PROTECTED_BRANCHES
        use_pr_workflow = (
            ENABLE_PR_WORKFLOW
            and (original_branch in GIT_PROTECTED_BRANCHES or is_leftover_feature_branch)
            and github_agent.gh_ready()
        )
        # Der eigentliche Ziel-/Basis-Branch für PR und neuen Feature-Branch – bei einem
        # Leftover-"feat/"-Branch NICHT original_branch selbst (der ist ja gerade das Problem),
        # sondern der erste konfigurierte Hauptbranch.
        base_branch = original_branch if original_branch in GIT_PROTECTED_BRANCHES else (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")
        feature_branch = github_agent.build_feature_branch_name(task_summary) if use_pr_workflow else None
        branch_note = (
            f"\n\n[bold cyan]🔀 PR-Workflow:[/bold cyan] Feature-Branch `{feature_branch}` wird "
            f"angelegt, gepusht und als Pull Request gegen `{base_branch}` geöffnet - "
            f"KEIN Direct-Commit auf `{base_branch}`."
            if use_pr_workflow else ""
        )

        # Realer Fund: JEDER Lauf endete bisher mit demselben "✅ Fertig!", egal ob die echte
        # Testsuite tatsächlich bestanden hatte, nie gefunden wurde, oder nach Fixversuchen
        # weiter fehlschlug – wer nur die letzte Statuszeile sah, hielt ungeprüften Code für
        # verifiziert. last_verification_ok (Orchestrator._run_verification_loop) macht den
        # Unterschied jetzt genau HIER sichtbar, wo eine irreversible Aktion (Push) ansteht.
        verification_ok = getattr(self._orchestrator, "last_verification_ok", False)
        report_hint = f" (Details: {self._last_report_path})" if self._last_report_path else ""
        verification_note = (
            "\n\n[bold yellow]⚠️ Nicht verifiziert:[/bold yellow] Die echte Testsuite hat diesen "
            f"Code NICHT bestätigt bestanden{report_hint}."
            if not verification_ok else ""
        )
        # Realer Fund: Rückfragen (core/agent_toolbox.py.ask_human_for_clarification) passierten
        # bisher nur VOR dem Start - eine mitten in der Aufgabe aufgetretene Blockade blieb im
        # Push-Gate unsichtbar, obwohl genau HIER die letzte Chance ist, sie vor einem Commit/PR
        # zu bemerken. Getrennt von verification_note: ein fehlgeschlagener Test und eine offene
        # fachliche Rückfrage sind unterschiedliche Gründe, nicht blind zu vertrauen.
        needs_human_input = getattr(self._orchestrator, "last_needs_human_input", False)
        clarification_questions = getattr(self._orchestrator, "last_clarification_questions", [])
        clarification_note = (
            "\n\n[bold cyan]❓ Offene Rückfrage(n):[/bold cyan]\n"
            + "\n".join(f"  • {q}" for q in clarification_questions)
            if needs_human_input else ""
        )

        console.print(
            Panel(
                (
                    f"[bold]{len(changed_files)} Datei(en) betroffen[/bold] "
                    f"(git add -A staged den GESAMTEN Repo-Stand, nicht nur dieses Projekt):\n\n"
                    + "\n".join(f"  {f}" for f in changed_files[:25])
                    + (f"\n  … und {len(changed_files) - 25} weitere" if len(changed_files) > 25 else "")
                    + (f"\n\n[dim]{diff_stat}[/dim]" if diff_stat else "")
                    + f"\n\n[bold]Geplante Commit-Message:[/bold]\n  {commit_msg}"
                    + branch_note
                    + verification_note
                    + clarification_note
                    + secret_note
                ),
                title="🔀 GitHub-Agent: Vorschau vor Commit & Push",
                border_style="red" if secret_findings else ("cyan" if (verification_ok and not needs_human_input) else "yellow"),
            )
        )
        try:
            if secret_findings:
                prompt = "🔑 Trotz möglicher Secret-Funde (siehe oben) wirklich committen und pushen?"
            elif needs_human_input:
                prompt = "Trotz offener Rückfrage(n) (siehe oben) committen und pushen?"
            elif verification_ok:
                prompt = "Möchtest du, dass ich GENAU DIESE Änderungen committe und auf GitHub pushe?"
            else:
                prompt = "Trotz NICHT bestandener/fehlender Verifikation committen und pushen?"
            should_push = Confirm.ask(prompt, default=False)
        except Exception:
            should_push = False

        if not should_push:
            console.print("↩️ Push übersprungen – nichts wurde committet oder gepusht.", style="dim")
            upsert_ticket(ticket_id=ticket_id, title=task_summary[:80], source="cli", status="done")
            return

        if use_pr_workflow:
            success_b, out_b = github_agent.create_branch(feature_branch, base=base_branch)
            if not success_b:
                console.print(
                    f"⚠️ Feature-Branch `{feature_branch}` konnte nicht angelegt werden ({out_b}) "
                    "– falle auf Direct-Push zurück.", style="yellow",
                )
                use_pr_workflow = False

        # Ticket-Endstatus wird unten je nach tatsächlichem Ausgang gesetzt (statt an jedem
        # Rückgabepunkt einzeln) - EIN upsert_ticket()-Aufruf am Ende deckt alle Pfade ab.
        ticket_status, ticket_detail = "blocked", ""

        success_c, out_c = github_agent.commit(commit_msg)
        if success_c:
            console.print(f"✅ [green]Commit erfolgreich:[/green] {commit_msg}")
            success_p, out_p = github_agent.push(branch=feature_branch if use_pr_workflow else None)
            if success_p:
                if use_pr_workflow:
                    console.print(f"🚀 [bold green]Feature-Branch `{feature_branch}` gepusht.[/bold green]")
                    # Realer Fund am Pong-Projekt: der PR-Titel/Body trug bisher UNTER KEINEN
                    # UMSTÄNDEN einen Hinweis auf den Verifikationsstatus - nur das Terminal
                    # (verification_note oben) warnte, aber genau das sieht ein Reviewer auf
                    # GitHub nie. Ein PR, dessen echte Testsuite nie bestätigt bestanden hat,
                    # bekommt jetzt einen unübersehbaren Titel-Präfix, das vollständige
                    # Verifikations-Protokoll im Body UND wird als Draft angelegt (github_agent.
                    # create_pull_request(draft=...)) - "noch nicht mergebereit" ist damit für
                    # GitHub selbst sichtbar, nicht nur im Fließtext, den man überlesen kann.
                    # needs_human_input reiht sich hier als ZWEITER, unabhängiger Grund für
                    # denselben Titel-Präfix/Draft-Mechanismus ein - eine offene Rückfrage ist
                    # kein Testfehler, verdient aber dieselbe Behandlung ("nicht blind mergen").
                    title_prefixes = []
                    if needs_human_input:
                        title_prefixes.append("❓ [RÜCKFRAGE]")
                    if not verification_ok:
                        title_prefixes.append("⚠️ [UNVERIFIZIERT]")
                    pr_title = f"{' '.join(title_prefixes)} {commit_msg}" if title_prefixes else commit_msg
                    verification_summary = getattr(self._orchestrator, "last_verification_summary", "") or ""
                    pr_body = f"Automatisch erstellt vom KI-Softwareentwickler-Team.\n\nAufgabe: {task_summary}"
                    if needs_human_input:
                        pr_body += (
                            "\n\n---\n\n❓ **Offene Rückfrage(n):** Mindestens eine Fachrolle hat NICHT "
                            "geraten, sondern gezielt nachgefragt - bitte beantworten:\n"
                            + "\n".join(f"- {q}" for q in clarification_questions)
                        )
                    if not verification_ok:
                        pr_body += (
                            "\n\n---\n\n⚠️ **Nicht verifiziert:** Die echte Testsuite hat diesen Code NICHT "
                            "bestätigt bestanden - vor dem Merge manuell prüfen.\n\n"
                            f"{verification_summary}"
                        )
                    success_pr, pr_out = github_agent.create_pull_request(
                        title=pr_title,
                        body=pr_body,
                        base=base_branch, head=feature_branch,
                        draft=not verification_ok or needs_human_input,
                    )
                    if success_pr:
                        pr_url = pr_out.splitlines()[-1] if pr_out else pr_out
                        console.print(f"🔀 [bold green]Pull Request erstellt:[/bold green] {pr_url}")
                        ticket_status, ticket_detail = "review", pr_url

                        # Realer Fund: Titel-Präfix und Body-Warnung (oben) sieht nur, wer den PR
                        # tatsächlich öffnet - in der PR-LISTE auf GitHub (wo ein Reviewer mehrere
                        # offene PRs überfliegt) war der Verifikationsstatus bisher unsichtbar.
                        # Labels erscheinen dort als eigene, farbige Chips. budget_aborted separat
                        # von verification_ok: ein vorzeitig wegen Budget beendeter Lauf ist ein
                        # anderer Grund zur Vorsicht als eine fehlgeschlagene Testsuite, auch wenn
                        # beide denselben Draft-Status auslösen.
                        status_labels = []
                        if not verification_ok:
                            status_labels.append("verification-failed")
                        if getattr(self._orchestrator, "last_budget_aborted", False):
                            status_labels.append("budget-aborted")
                        if needs_human_input:
                            status_labels.append("needs-clarification")
                        if status_labels:
                            success_label, label_out = github_agent.label_pr(pr_url, status_labels)
                            if not success_label:
                                console.print(
                                    f"⚠️ Label(s) {status_labels} konnten nicht gesetzt werden ({label_out}) "
                                    "– PR bleibt trotzdem bestehen.", style="dim yellow",
                                )

                        # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-
                        # Kommentare): unbehobene kritische Governance-/Permission-Blocked-Funde
                        # (self._orchestrator.last_unresolved_review_findings, siehe dessen
                        # Docstring in agents/orchestrator/__init__.py) landeten bisher nur im
                        # unresolved-*-Backlog-Ticket, unsichtbar für einen Reviewer, der nur den
                        # PR selbst öffnet. Postet sie jetzt zusätzlich als echten, dateibezogenen
                        # GitHub-Review (agents/github_agent.py.post_pr_review()).
                        unresolved_findings = getattr(self._orchestrator, "last_unresolved_review_findings", [])
                        if unresolved_findings:
                            success_review, review_out = github_agent.post_pr_review(pr_url, unresolved_findings)
                            if success_review:
                                console.print(
                                    f"🔎 [dim]{len(unresolved_findings)} unbehobene(r) kritische(r) "
                                    "Befund(e) als PR-Review-Kommentar hinterlassen.[/dim]"
                                )
                            else:
                                console.print(
                                    f"⚠️ [dim yellow]PR-Review-Kommentar konnte nicht gepostet werden: "
                                    f"{review_out}[/dim yellow]"
                                )
                    else:
                        console.print(
                            f"⚠️ PR-Erstellung fehlgeschlagen ({pr_out}) – Branch ist trotzdem "
                            "gepusht, PR ggf. manuell auf GitHub anlegen.", style="yellow",
                        )
                        ticket_detail = pr_out
                else:
                    console.print("🚀 [bold green]Änderungen erfolgreich auf GitHub gepusht![/bold green]")
                    ticket_status = "done"
                # Realer Fund: das CI-Ergebnis wurde bisher nur angezeigt, nie ausgewertet - ein
                # eröffneter PR/Direct-Push blieb im Backlog auf "review"/"done" stehen, selbst
                # wenn die echte CI-Pipeline danach tatsächlich rot wurde. Rote CI zieht den
                # Ticket-Status jetzt auf "blocked" (braucht menschliche Aufmerksamkeit), bevor
                # jemand versehentlich einen kaputten PR mergt. "passed"/"timeout"/"no_run"
                # ändern nichts am bisherigen Verhalten.
                ci_status, ci_detail = await self._report_ci_status(github_agent)
                if ci_status == "failed":
                    ticket_status = "blocked"
                    ticket_detail = f"{ticket_detail} | CI fehlgeschlagen: {ci_detail}" if ticket_detail else f"CI fehlgeschlagen: {ci_detail}"
            else:
                console.print(f"⚠️ Push nicht abgeschlossen: {out_p}", style="yellow")
                ticket_detail = out_p
        else:
            console.print(f"⚠️ Commit nicht möglich: {out_c}", style="yellow")
            ticket_detail = out_c

        upsert_ticket(
            ticket_id=ticket_id, title=task_summary[:80], source="cli",
            status=ticket_status, detail=ticket_detail[:300],
        )

    async def _report_ci_status(self, github_agent) -> tuple[str, str]:
        """
        Wartet auf die echte CI-Pipeline (.github/workflows/ci.yml, läuft bei jedem Push) und
        meldet das tatsächliche Ergebnis – realer Fund: push() war bisher "fire and forget",
        ob CI tatsächlich grün wurde, hat das Team nie erfahren. Ein `no_run`-Ergebnis (kein
        `gh` verfügbar, kein GitHub-Remote, ...) ist dabei kein Fehler, nur nicht prüfbar.

        Gibt (status, detail) zurück – zweiter realer Fund: das Ergebnis wurde bisher nur
        angezeigt, nie ausgewertet. _ask_for_git_push() nutzt es jetzt, um den Backlog-Ticket-
        Status bei roter CI auf "blocked" zu ziehen, statt bei "review"/"done" stehen zu bleiben.
        """
        from interface.cli import notify_external
        branch = github_agent.get_current_branch()
        console.print(f"🔄 [dim]Warte auf CI-Status für `{branch}` (max. 90s)...[/dim]")
        status, detail = await github_agent.wait_for_ci_status(branch)
        if status == "passed":
            console.print(f"✅ [bold green]CI grün:[/bold green] {detail}")
        elif status == "failed":
            console.print(f"❌ [bold red]CI fehlgeschlagen:[/bold red] {detail}", style="red")
            await asyncio.to_thread(notify_external, "CI fehlgeschlagen", f"Branch `{branch}`: {detail}")
        elif status == "timeout":
            console.print(f"⏳ [yellow]{detail}[/yellow] – prüfe den Status später manuell.")
        else:  # "no_run"
            console.print(f"ℹ️ [dim]CI-Status nicht prüfbar: {detail}[/dim]")
        return status, detail

    async def _create_release_with_confirmation(self) -> None:
        """
        Echtes Release-Management: leitet den nächsten SemVer-Bump aus den tatsächlichen
        Commit-Messages seit dem letzten Tag ab (core/framework_release.py, nutzt die im
        Projekt bereits etablierte feat:/fix:-Konvention) und erstellt bei Bestätigung einen
        echten Git-Tag + eine echte GitHub-Release. Realer Fund bei einer Bestandsaufnahme
        des eigenen Teams: CHANGELOG.md wird bei jedem PR manuell gepflegt, aber es gab über
        die gesamte Projekthistorie keine einzige Versionsnummer, keinen Git-Tag, keine
        GitHub-Release – nur eine hart einprogrammierte Zeichenkette im README.
        """
        github_agent = self._orchestrator._agents.get("github")
        if not github_agent or not github_agent.gh_ready():
            console.print("⚠️ `gh`-CLI nicht verfügbar/eingeloggt – Release braucht echten GitHub-Zugriff.", style="yellow")
            return

        latest_tag = framework_release.get_latest_tag()
        commits = framework_release.get_commits_since(latest_tag)
        bump = framework_release.determine_version_bump(commits)
        if bump is None:
            console.print(
                f"ℹ️ Keine neuen Commits seit `{latest_tag or '(noch kein Release)'}` – nichts zu releasen.",
                style="dim",
            )
            return

        next_version = framework_release.bump_version(latest_tag or "v0.0.0", bump)
        notes = framework_release.build_release_notes(commits)
        console.print(
            Panel(
                f"[bold green]{latest_tag or '(kein bisheriger Release)'} → {next_version}[/bold green] "
                f"({bump}-Bump, {len(commits)} Commit(s) seit dem letzten Release)\n\n{notes}",
                title="🏷️ Release: Vorschau", border_style="green",
            )
        )
        try:
            should_release = Confirm.ask(f"Release `{next_version}` WIRKLICH erstellen (echter Tag + GitHub-Release)?", default=False)
        except Exception:
            should_release = False
        if not should_release:
            console.print("↩️ Release abgebrochen.", style="dim")
            return

        success, output = framework_release.create_release(next_version, notes)
        if success:
            console.print(f"🏷️ [bold green]Release {next_version} erstellt:[/bold green] {output}")
        else:
            console.print(f"⚠️ Release nicht vollständig erstellt: {output}", style="yellow")

    async def _rollback_merged_pr(self, pr_number_str: str) -> None:
        """
        Echter Rollback-Workflow: revertiert den Merge-Commit eines bereits gemergten PRs auf
        einem eigenen Branch und öffnet dafür einen ganz normalen Revert-Pull-Request – KEIN
        Direct-Commit auf den Hauptbranch, derselbe PR-Workflow wie jede andere Änderung.
        Realer Fund bei einer Bestandsaufnahme des eigenen Teams: bricht ein gemergter PR
        `main` (z.B. rotes CI erst nach dem Merge bemerkt), gab es dafür bisher keinen
        Mechanismus – nur der manuelle Weg direkt über GitHub.
        """
        github_agent = self._orchestrator._agents.get("github")
        if not github_agent:
            console.print("⚠️ GitHub-Agent nicht verfügbar.", style="yellow")
            return
        if not github_agent.gh_ready():
            console.print("⚠️ `gh`-CLI nicht verfügbar/eingeloggt – Rollback braucht echten GitHub-Zugriff.", style="yellow")
            return
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            console.print(f"⚠️ '{pr_number_str}' ist keine gültige PR-Nummer.", style="yellow")
            return

        found, sha_or_error, title = github_agent.get_merged_pr_info(pr_number)
        if not found:
            console.print(f"⚠️ Rollback nicht möglich: {sha_or_error}", style="yellow")
            return

        base_branch = GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main"
        console.print(
            Panel(
                f"[bold red]Erstellt einen echten Revert-Commit für PR #{pr_number}[/bold red]\n\n"
                f"  Titel: {title}\n"
                f"  Merge-Commit: `{sha_or_error[:12]}`\n\n"
                f"Legt einen neuen Branch von `{base_branch}` an, revertiert den Merge-Commit "
                f"darauf und öffnet einen Revert-Pull-Request – merged NICHTS automatisch, "
                f"CI/Review laufen wie bei jedem anderen PR.",
                title="↩️ Rollback: Vorschau", border_style="red",
            )
        )
        try:
            should_rollback = Confirm.ask(f"PR #{pr_number} WIRKLICH per Revert-PR zurückrollen?", default=False)
        except Exception:
            should_rollback = False
        if not should_rollback:
            console.print("↩️ Rollback abgebrochen.", style="dim")
            return

        original_branch = github_agent.get_current_branch()
        revert_branch = f"revert-{pr_number}-{uuid.uuid4().hex[:6]}"

        success_b, out_b = github_agent.create_branch(revert_branch, base=base_branch)
        if not success_b:
            console.print(f"⚠️ Revert-Branch konnte nicht angelegt werden: {out_b}", style="yellow")
            return

        success_r, out_r = github_agent.revert_commit(sha_or_error)
        if not success_r:
            console.print(f"⚠️ Revert fehlgeschlagen (evtl. Konflikt mit späteren Änderungen): {out_r}", style="red")
            github_agent.checkout(original_branch)
            return

        success_p, out_p = github_agent.push(branch=revert_branch)
        if not success_p:
            console.print(f"⚠️ Push des Revert-Branches fehlgeschlagen: {out_p}", style="yellow")
            return

        success_pr, pr_out = github_agent.create_pull_request(
            title=f"Revert: {title} (#{pr_number})",
            body=f"Automatischer Rollback von PR #{pr_number} über `/rollback`.\n\n"
                 f"Ursprünglicher Merge-Commit: {sha_or_error}",
            base=base_branch, head=revert_branch,
        )
        if success_pr:
            pr_url = pr_out.splitlines()[-1] if pr_out else pr_out
            console.print(f"↩️ [bold green]Revert-Pull-Request erstellt:[/bold green] {pr_url}")
            upsert_ticket(
                ticket_id=new_ticket_id("cli"), title=f"Revert: {title[:70]}", source="cli",
                status="review", detail=pr_url,
            )
        else:
            console.print(
                f"⚠️ Revert-PR-Erstellung fehlgeschlagen ({pr_out}) – Branch `{revert_branch}` "
                "ist trotzdem gepusht, PR ggf. manuell auf GitHub anlegen.", style="yellow",
            )

    def _prune_worktrees(self) -> None:
        """
        Räumt verwaiste, vom KI-Team angelegte Git-Isolations-Worktrees (siehe
        core/git_isolation.py) auf: bereits gemergte oder seit 7+ Tagen inaktive Worktrees
        werden entfernt (der aktuell aktive Worktree und alles mit ungemergten Änderungen
        bleibt garantiert unangetastet).
        """
        from config import BASE_DIR
        from core.git_isolation import find_git_root, prune_stale_worktrees

        git_root = find_git_root(BASE_DIR)
        if not git_root:
            console.print("⚠️ Kein Git-Repository gefunden - nichts zum Aufräumen.", style="yellow")
            return

        console.print("🧹 [bold cyan]Prüfe auf verwaiste KI-Team-Worktrees...[/bold cyan]")
        actions = prune_stale_worktrees(git_root)

        if not actions:
            console.print("✅ Keine verwaisten Worktrees gefunden.", style="green")
            return

        removed = [a for a in actions if a.action == "removed"]
        skipped = [a for a in actions if a.action == "skipped"]

        if removed:
            lines = [f"  🗑️ {a.branch} ({a.path})\n     Grund: {a.reason}" for a in removed]
            console.print(
                Panel("\n".join(lines), title=f"Entfernt ({len(removed)})", border_style="green")
            )
        if skipped:
            lines = [f"  ⏭️ {a.branch} ({a.path})\n     Grund: {a.reason}" for a in skipped]
            console.print(
                Panel("\n".join(lines), title=f"Übersprungen ({len(skipped)})", border_style="yellow")
            )

    async def _protect_branch_with_confirmation(self, branch: str | None) -> None:
        """
        Aktiviert echte GitHub-Branch-Protection (agents/github_agent.py.set_branch_protection())
        für `branch` (Standard: der erste konfigurierte GIT_PROTECTED_BRANCHES-Eintrag, i.d.R.
        "main") – mit Vorschau + Bestätigung, analog zu /deploy: eine Änderung an den
        Repo-Einstellungen selbst über die GitHub-API ist ein bewusster, schwer beiläufig
        rückgängig zu machender Schritt, verdient dieselbe Bestätigungs-Gate-Philosophie statt
        stillschweigend loszulaufen. Realer struktureller Fund: der PR-Workflow verhindert nur,
        dass DIESES Tool direkt auf den Hauptbranch pusht – ohne dieses Kommando könnte ein
        Mensch (oder ein anderes Tool) weiterhin `git push origin main` direkt ausführen.
        """
        target_branch = branch or (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")
        github_agent = self._orchestrator._agents.get("github")
        if github_agent is None or not github_agent.gh_ready():
            console.print(
                "⚠️ `gh`-CLI nicht installiert/nicht eingeloggt – Branch-Protection kann nicht "
                "gesetzt werden. Prüfe `gh auth status`.", style="yellow",
            )
            return

        console.print(
            Panel(
                f"[bold]Branch:[/bold] `{target_branch}`\n"
                f"[bold]Pflicht-Freigaben vor Merge:[/bold] {BRANCH_PROTECTION_REQUIRED_REVIEWS}\n"
                "[bold]Zusätzlich:[/bold] kein Force-Push, keine Branch-Löschung, gilt auch für Repo-Admins.\n"
                "[dim]Erfordert Admin-Rechte auf dem Repo (die aktuelle `gh`-Anmeldung).[/dim]",
                title="🔒 Branch-Protection: Vorschau",
                border_style="cyan",
            )
        )
        try:
            should_apply = Confirm.ask(f"Branch-Protection für `{target_branch}` wirklich aktivieren?", default=False)
        except Exception:
            should_apply = False
        if not should_apply:
            console.print("↩️ Übersprungen.", style="dim")
            return

        success, output = await asyncio.to_thread(
            github_agent.set_branch_protection, target_branch, BRANCH_PROTECTION_REQUIRED_REVIEWS,
        )
        if success:
            console.print(f"✅ [bold green]Branch-Protection für `{target_branch}` aktiviert.[/bold green]")
        else:
            console.print(f"❌ [bold red]Fehlgeschlagen:[/bold red]\n{output}", style="red")

