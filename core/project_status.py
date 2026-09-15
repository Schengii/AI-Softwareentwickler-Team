"""
core/project_status.py – Persistenter Projekt-Status für Kontinuität über mehrere Sitzungen

Realer Fund: memory/conversation_history.py ist SITZUNGS-gebunden (memory/history_<session>.json)
– startet der Nutzer eine neue Sitzung (neues Terminal), ist jeglicher Kontext über ein
Projekt weg, selbst wenn er per `/load` dasselbe Projekt erneut öffnet. Ein Mensch, der ein
Projekt nach Tagen wieder aufmacht, hat wenigstens ein Commit-Log oder eigene Notizen – das
Team hatte bisher nur die rohen Quelldateien, ohne jede Historie oder Hinweis auf offene
Punkte (z.B. "Lauf-Budget während der Verifikation erreicht, letzter Stand nicht grün").

Schreibt/liest eine kompakte JSON-Historie direkt im Projektverzeichnis (bewusst NICHT
gitignored – im Unterschied zu .ai_team_venv/.ai_team_rag ist das echte, wertvolle
Projekt-Historie, kein Build-Artefakt, und soll mitversioniert werden).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from core.run_trace import read_run_artifact, write_verification_protocol

STATUS_FILENAME = ".ai_team_status.json"
STATE_MD_FILENAME = "PROJECT_STATE.md"
# Ungekürztes Verifikationsprotokoll jedes Laufs, ausschließlich für manuelle Diagnose (siehe
# MAX_FAILURE_DETAIL_CHARS unten) - wird NIE in einen Agenten-Prompt geladen, deshalb ohne
# Zeichenbudget. Bisher musste dafür core.verifier.ProjectVerifier live gegen das Projekt
# erneut ausgeführt werden, weil .ai_team_status.json nur die gekappte Version persistiert -
# gerade der entscheidende Teil einer langen Fehlermeldung fiel dabei regelmäßig der Kappung
# zum Opfer (z.B. der Frontend-404-Befund im snippet_vault-Projekt, der erst nach manuellem
# Nachstellen sichtbar wurde).
FULL_LOG_FILENAME = ".ai_team_status_full.log"
MAX_HISTORY_ENTRIES = 10

# Deckelt .ai_team_status_full.log (siehe _append_full_log unten) auf eine sinnvolle Größe.
# Anders als .ai_team_status.json (auf MAX_HISTORY_ENTRIES Einträge UND MAX_FAILURE_DETAIL_CHARS
# je Eintrag gedeckelt) protokolliert das Full-Log JEDEN Lauf mit dem ungekürzten
# verification_summary - wertvoll für eine spätere tiefe Fehleranalyse, aber ohne Deckel würde
# die Datei bei einem langlebigen Projekt mit vielen Läufen unbegrenzt wachsen. 5 MB ist
# großzügig genug für hunderte Läufe, aber klein genug, um kein Repo-Gewicht-Problem zu werden.
MAX_FULL_LOG_BYTES = 5 * 1024 * 1024

# Wie viele Zeichen des rohen Verifikations-Reports (verification_summary aus
# agents/orchestrator.py) in der Lauf-Historie gespeichert werden. Realer Fund: bisher wurde
# nur der Boolean verification_ok persistiert - bei wiederholt fehlschlagenden Läufen an
# demselben Projekt (z.B. api_health_monitor: 4 Läufe in Folge, davon einer per Budget
# abgebrochen) hatte kein künftiger Agent Zugriff auf die KONKRETE Fehlermeldung des letzten
# Versuchs und wiederholte denselben vollen (kostenpflichtigen) Lauf, statt gezielt den
# bekannten Fehler zu beheben. Gedeckelt wie MAX_RULE_LENGTH in
# memory/agent_knowledge_base.py, aus demselben Grund (Tokenverbrauch bei jeder künftigen
# Injektion in format_context_for_agents).
MAX_FAILURE_DETAIL_CHARS = 500

# Wie viele Lint-Fund-Signaturen ("tool:datei:regel") pro Lauf in der Historie gespeichert
# werden - Grundlage für has_repeated_lint_finding() unten. Realer Fund (Team-Retrospektive,
# omnichat-Projekt): derselbe Lint-Fund (ruff F841) blieb über DREI aufeinanderfolgende volle
# Läufe unverändert bestehen, weil Lint bewusst rein informativ ist (siehe
# core/verifier/lint.py) und deshalb NIE verification_ok beeinflusst - has_repeated_failure()
# griff dadurch nie, egal wie oft sich derselbe Lint-Fund wiederholte. 20 reicht für einen
# aussagekräftigen Fingerabdruck, ohne die Historie-Datei unnötig aufzublähen.
MAX_LINT_SIGNATURE_ITEMS = 20

# Team-Optimierung (Retrospektive 2026-09-03): ein Projekt (mockforge) wurde in
# PROJECT_STATE.md als "✅ Vollständig verifiziert & einsatzbereit" ausgewiesen, obwohl
# agents/orchestrator/verification.py für genau dieses Projekt kurz zuvor ein "blocked"-Ticket
# zu einem NICHT behobenen kritischen Befund eröffnet hatte (die reale Testsuite bestand zwar,
# das kritische Architektur-/Sicherheitsproblem aus dem Governance-Review blieb aber im Code
# bestehen) - verification_ok (nur "laufen die Tests?") und der offene kritische Befund
# (core/backlog_store.py-Ticket) waren bisher komplett entkoppelt. _open_blocker_ticket()
# schließt diese Lücke: der Status-Badge berücksichtigt jetzt BEIDES.
_BLOCKER_TICKET_PREFIXES = ("unresolved-governance-critical-", "unresolved-permission-blocked-")

# Team-Optimierung (Retrospektive 2026-09-05, logpulse-Nachlauf): "recurring-failure-<slug>"-
# Tickets (agents/orchestrator/verification.py._run_verification_loop, dort per
# `had_prior_test_ticket` geschlossen) wurden bisher AUSSCHLIESSLICH innerhalb GENAU DES Laufs
# geschlossen, dessen eigene interne Fix-Schleife bis zu einem erneut grünen Testlauf iterierte.
# Wurde das zugrunde liegende Problem stattdessen AUSSERHALB dieser einen Schleife behoben (z.B.
# ein manueller Fix zwischen zwei Läufen, oder ein späterer Lauf ist gleich beim allerersten
# Testlauf grün, ohne dass die Schließlogik in verification.py für DIESES Ticket je erneut
# durchlaufen wird), blieb das Ticket für immer "blocked" stehen, obwohl das Projekt auf der
# Platte längst wieder grün war (real beobachtet: workspace/logpulse - requirements.txt/
# pytest.ini/app/main.py wurden außerhalb eines Orchestrator-Laufs repariert, `pytest` bestand
# danach nachweislich, das Ticket blieb trotzdem offen). _open_blocker_ticket() prüft deshalb
# jetzt, genau wie bei den _BLOCKER_TICKET_PREFIXES-Tickets oben, bei JEDEM Checkpoint mit
# verification_ok=True zusätzlich, ob ein offenes "recurring-failure-"-Ticket für dieses Projekt
# existiert - verification_ok bedeutet hier bereits "die echte Testsuite ist in DIESEM Lauf
# tatsächlich grün", das allein reicht als Beleg (kein weiterer check_completeness()-Aufruf nötig,
# der prüft nur strukturelle Vollständigkeit, keine Testergebnisse).
_RECURRING_FAILURE_TICKET_PREFIX = "recurring-failure-"


def _open_blocker_ticket(project_dir: str, verification_ok: bool = False):
    """Gibt das offene ("blocked") Governance-/Verifikations-Ticket dieses Projekts zurück,
    falls eines existiert - None sonst. Ein Lookup-Fehler (z.B. eine kaputte
    memory/backlog.json) darf die Checkpoint-Erstellung nie zum Absturz bringen, dieselbe
    defensive Haltung wie bei _prior_run_context() in agents/orchestrator/verification.py.

    Team-Optimierung (Retrospektive, zeiterfassung_app-Lauf): ein Ticket wird bisher NUR über
    agents/orchestrator/verification.py._run_governance_fix_loop() geschlossen - dort ausschließlich
    durch einen erneuten, expliziten Recheck derselben Governance-Rollen (code_reviewer/security/
    compliance). Wird das zugrunde liegende Problem stattdessen auf einem anderen Weg behoben
    (z.B. ein direkt beauftragter Folge-Chat, der die fehlenden Dateien anlegt, ohne dass die
    Governance-Rollen erneut liefen), bleibt das Ticket ewig "blocked" im Backlog stehen, obwohl
    das Projekt auf der Platte längst repariert ist - PROJECT_STATE.md zeigte dadurch real
    "🔴 Kritischer Befund ungelöst", obwohl `app/routers/` und `app/dependencies.py` bereits
    existierten. Bei jedem Checkpoint mit BESTANDENER Testsuite wird deshalb zusätzlich der
    günstige, rein statische Vollständigkeits-Check (core/verifier/completeness.py, Millisekunden,
    kein LLM-Aufruf) als Ground-Truth herangezogen: findet er keine Stub-/Missing-Import-/Manifest-
    Funde mehr, gilt das Ticket als eigenständig gelöst und wird automatisch geschlossen, statt der
    reinen Ticket-Statuszeile blind zu vertrauen. Dieselbe Ground-Truth-Re-Verifikation gilt seit
    der logpulse-Retrospektive (siehe _RECURRING_FAILURE_TICKET_PREFIX oben) zusätzlich für
    "recurring-failure-"-Tickets, dort genügt bereits ein grünes verification_ok dieses Laufs."""
    try:
        from core.backlog_store import list_tickets, upsert_ticket
    except Exception:
        return None
    slug = Path(project_dir).name
    try:
        blocked_tickets = [t for t in list_tickets(status="blocked") if t.project_slug == slug]
    except Exception:
        return None

    ticket = next((t for t in blocked_tickets if t.id.startswith(_BLOCKER_TICKET_PREFIXES)), None)
    recurring_failure_ticket = next(
        (t for t in blocked_tickets if t.id.startswith(_RECURRING_FAILURE_TICKET_PREFIX)), None,
    )

    if verification_ok and recurring_failure_ticket is not None:
        try:
            upsert_ticket(
                ticket_id=recurring_failure_ticket.id, title=recurring_failure_ticket.title,
                source=recurring_failure_ticket.source, status="done",
                project_slug=recurring_failure_ticket.project_slug,
                detail="Eigenständig behoben (dieser Checkpoint bestätigt eine erneut grüne "
                       "Testsuite) - automatisch erkannt und geschlossen, ohne auf denselben Lauf "
                       "zu warten, der das Ticket ursprünglich eröffnet hat.",
            )
            recurring_failure_ticket = None
        except Exception:
            pass

    if ticket is not None and verification_ok:
        try:
            from core.verifier import ProjectVerifier
            report = ProjectVerifier(project_dir).check_completeness()
            if report.attempted and report.passed:
                upsert_ticket(
                    ticket_id=ticket.id, title=ticket.title, source=ticket.source,
                    status="done", project_slug=ticket.project_slug,
                    detail="Eigenständig behoben (statischer Vollständigkeits-Check findet keine "
                           "offenen Funde mehr) - automatisch beim nächsten Checkpoint erkannt und "
                           "geschlossen, ohne einen erneuten Governance-Recheck abzuwarten.",
                )
                ticket = None
        except Exception:
            pass

    # Governance-/Berechtigungs-Tickets zuerst (schwerwiegender, ausführlicherer Befundtext) -
    # ein weiterhin offenes "recurring-failure-"-Ticket wird nur angezeigt, wenn KEIN Governance-
    # Ticket mehr offen ist, dieselbe Priorisierung wie beim Status-Badge in
    # generate_project_state_md() unten (ein einzelnes Ticket wird dort dargestellt).
    return ticket or recurring_failure_ticket


def _status_path(project_dir: str) -> Path:
    return Path(project_dir) / STATUS_FILENAME


def _full_log_path(project_dir: str) -> Path:
    return Path(project_dir) / FULL_LOG_FILENAME


def _state_md_path(project_dir: str) -> Path:
    return Path(project_dir) / STATE_MD_FILENAME


def _append_full_log(project_dir: str, entry: dict) -> None:
    """Hängt diesen Lauf UNGEKÜRZT (kein MAX_FAILURE_DETAIL_CHARS-Deckel wie in record_run) an
    .ai_team_status_full.log an - eine reine Nachschlage-Historie für tiefe Fehleranalyse über
    viele Läufe hinweg, getrennt von der kompakten, gedeckelten .ai_team_status.json.

    Rotiert die Datei, sobald sie MAX_FULL_LOG_BYTES überschreitet: die ÄLTESTEN Blöcke (am
    Dateianfang, da neue Einträge angehängt werden) werden verworfen, bis die Datei wieder
    unter der Schwelle liegt - nie die ganze Datei gelöscht, nur so viel wie nötig."""
    separator = "=" * 80
    block_lines = [separator, f"Zeitstempel: {entry.get('timestamp', '?')}"]
    block_lines.append(f"Aufgabe: {entry.get('task_summary', '?')}")
    status_bits = []
    if entry.get("verification_ok"):
        status_bits.append("verifiziert")
    if entry.get("budget_aborted"):
        status_bits.append("budget_aborted")
    if entry.get("cancelled"):
        status_bits.append("cancelled")
    block_lines.append(f"Status: {', '.join(status_bits) if status_bits else 'nicht verifiziert'}")
    detail = entry.get("failure_detail") or entry.get("success_detail")
    if detail:
        block_lines.append(detail)
    block = "\n".join(block_lines) + "\n"

    path = _full_log_path(project_dir)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError:
        return

    try:
        _rotate_full_log(path)
    except OSError:
        pass


def _rotate_full_log(path: Path) -> None:
    """Kappt eine zu groß gewordene Full-Log-Datei, indem die ältesten Blöcke (jeder beginnt
    mit der 80-Zeichen "="-Trennzeile) verworfen werden, bis die Datei wieder unter
    MAX_FULL_LOG_BYTES liegt - die neuesten Einträge bleiben dabei vollständig erhalten."""
    if not path.exists() or path.stat().st_size <= MAX_FULL_LOG_BYTES:
        return

    separator = "=" * 80
    content = path.read_text(encoding="utf-8")
    # Jeder Block beginnt mit der Trennzeile - split() liefert daher ein leeres erstes Element,
    # gefolgt von den eigentlichen Blöcken (jeweils ohne die führende Trennzeile).
    raw_blocks = content.split(separator + "\n")
    blocks = [separator + "\n" + b for b in raw_blocks if b.strip()]

    # Älteste zuerst verwerfen, bis die verbleibenden Blöcke unter die Schwelle passen -
    # mindestens der jüngste Block bleibt immer erhalten, selbst wenn er allein schon größer
    # als die Schwelle ist (kein Datenverlust des aktuellsten Laufs).
    while len(blocks) > 1 and sum(len(b.encode("utf-8")) for b in blocks) > MAX_FULL_LOG_BYTES:
        blocks.pop(0)

    path.write_text("".join(blocks), encoding="utf-8")


def read_status(project_dir: str) -> list[dict]:
    """Gibt die protokollierte Lauf-Historie dieses Projekts zurück (neueste zuerst) – leere
    Liste, falls noch keine existiert oder die Datei beschädigt ist (kein Crash)."""
    path = _status_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def read_project_state_md(project_dir: str) -> str:
    """Liest die PROJECT_STATE.md des Projekts ein – leerer String, falls noch keine existiert."""
    path = _state_md_path(project_dir)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def generate_project_state_md(
    project_dir: str,
    task_summary: str = "",
    verification_ok: bool = False,
    budget_aborted: bool = False,
    cancelled: bool = False,
    files_written: list[str] | None = None,
    next_steps: list[str] | None = None,
    provider_exhausted: bool = False,
) -> str:
    """Generiert einen kompakten, token-effizienten PROJECT_STATE.md-Bericht für das Projekt."""
    p_path = Path(project_dir)
    project_name = p_path.name or "Projekt"

    blocker_ticket = _open_blocker_ticket(project_dir, verification_ok=verification_ok)

    # Status-Badge. Ein offenes Governance-/Verifikations-Ticket überschreibt JEDEN anderen
    # Status inkl. einer bestandenen Testsuite (verification_ok=True) - ein kritischer,
    # nachweislich ungelöster Befund macht ein Projekt nicht "einsatzbereit", nur weil die
    # Tests grün sind (siehe Modul-Kommentar zu _BLOCKER_TICKET_PREFIXES oben).
    # Team-Optimierung (chronos_queue-Retrospektive, 20260911): ein Lauf, der wegen einer
    # Kontingent-/Guthaben-Erschöpfung ALLER Provider abgebrochen wurde (Fast Circuit Breaker,
    # agents/orchestrator/department.py), sah bisher wie jeder andere "🚫 Lauf-Budget erreicht"-
    # Abbruch aus - der Unterschied ist entscheidend: kein Mensch muss hier eine Aufgabe
    # verkleinern, sondern schlicht Kontingent/Guthaben nachlegen, bevor ein Folgelauf überhaupt
    # Sinn ergibt. Verwaiste Teil-Artefakte (z.B. nur Frontend, kein Backend) müssen VOR dem
    # nächsten Lauf explizit bereinigt oder bewusst fortgesetzt werden.
    if blocker_ticket:
        status_label = "🔴 Kritischer Befund ungelöst – NICHT einsatzbereit (Backlog-Ticket offen)"
    elif verification_ok:
        status_label = "✅ Vollständig verifiziert & einsatzbereit"
    elif cancelled:
        status_label = "⏹️ Lauf manuell pausiert"
    elif budget_aborted and provider_exhausted:
        status_label = "🛑 Abgebrochen wegen Provider-Kontingent-Erschöpfung – UNVOLLSTÄNDIG (vor nächstem Lauf bereinigen/fortsetzen!)"
    elif budget_aborted:
        status_label = "🚫 Lauf-Budget erreicht (Teilstand gesichert)"
    else:
        status_label = "⚠️ In Entwicklung / Verifikation ausstehend"

    # Dateien ermitteln
    existing_files: list[str] = []
    try:
        for f in p_path.rglob("*"):
            if f.is_file() and not any(part.startswith((".", "__pycache__", "node_modules", "venv")) for part in f.parts):
                rel = f.relative_to(p_path).as_posix()
                if rel != STATE_MD_FILENAME and rel != STATUS_FILENAME:
                    existing_files.append(rel)
    except OSError:
        pass

    now_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# 📌 {project_name} – Projekt-Status & Checkpoint",
        "",
        f"- **Letzte Aktualisierung:** `{now_iso}`",
        f"- **Aktueller Status:** {status_label}",
        f"- **Zuletzt bearbeitete Aufgabe:** {task_summary or 'Projekt-Initialisierung'}",
        "",
        "## 📁 Wichtige Projektkomponenten & Dateien",
    ]

    if existing_files:
        for f in sorted(existing_files)[:20]:
            lines.append(f"- `{f}`")
        if len(existing_files) > 20:
            lines.append(f"- *... und {len(existing_files) - 20} weitere Dateien*")
    else:
        lines.append("- *(Noch keine Quellcodedateien angelegt)*")

    lines += [
        "",
        "## 🧪 Verifikations- & Test-Status",
        f"- **Tests bestanden:** {'Ja ✅' if verification_ok else 'Ausstehend / Fehlgeschlagen ⚠️'}",
    ]

    if budget_aborted and provider_exhausted:
        lines += [
            "",
            "## 🛑 Lauf wegen Provider-Kontingent-Erschöpfung abgebrochen",
            "- **Dieses Projekt ist UNVOLLSTÄNDIG.** Mehrere Agenten in Folge (bzw. eine kritische "
            "Rolle wie `architect`/`backend`) scheiterten daran, dass KEIN konfigurierter "
            "KI-Provider mehr Kapazität/Guthaben hatte - der Lauf wurde deshalb sofort beendet, "
            "statt weiter sinnlos Tokens für garantiert scheiternde Aufrufe zu verbrauchen.",
            "- Die oben gelisteten Dateien sind daher möglicherweise nur ein Teilstand (z.B. "
            "Frontend ohne Backend) - vor dem nächsten Lauf entweder gezielt bereinigen "
            "(unvollständige/verwaiste Artefakte entfernen) oder den Lauf bewusst fortsetzen.",
            "- Details, welcher Provider warum ausgefallen ist, stehen im CLI-Abschlussbericht "
            "des abgebrochenen Laufs (agents/orchestrator/reporting.py).",
        ]

    if blocker_ticket:
        lines += [
            "",
            "## 🔴 Offener kritischer Befund (Backlog-Ticket)",
            f"- **Ticket:** `{blocker_ticket.id}` (Status: `{blocker_ticket.status}`, "
            f"bisherige Wiederholungsversuche: {blocker_ticket.retries})",
            "- **Befund:**",
            f"  > {blocker_ticket.detail[:400] or '(kein Detailtext hinterlegt)'}",
            "- Dieses Projekt gilt trotz einer eventuell bestandenen Testsuite NICHT als "
            "einsatzbereit, solange dieses Ticket offen ist. `python main.py --work-backlog` "
            "greift es automatisch erneut auf (begrenzte Anzahl Versuche, siehe "
            "config.MAX_GOVERNANCE_TICKET_RETRIES).",
        ]

    lines += [
        "",
        "## 🎯 Nächste empfohlene Schritte (Next Actions)",
    ]

    if next_steps:
        for i, step in enumerate(next_steps, start=1):
            lines.append(f"{i}. {step}")
    elif budget_aborted and provider_exhausted:
        lines.append("1. Provider-Kontingent/Guthaben auffüllen (siehe CLI-Abschlussbericht des abgebrochenen Laufs für Details je Provider).")
        lines.append("2. Unvollständige Teil-Artefakte dieses Laufs bereinigen ODER den Lauf gezielt fortsetzen.")
        lines.append("3. Erst danach einen neuen Lauf starten - `python main.py` prüft die Kapazität vorab erneut (core/capacity_gate.py).")
    elif blocker_ticket:
        lines.append(f"1. Offenen kritischen Befund aus Ticket `{blocker_ticket.id}` beheben (siehe oben).")
        lines.append("2. Danach `/run-tests` bzw. einen neuen Lauf anstoßen, um das Ticket zu schließen.")
    else:
        if not verification_ok:
            lines.append("1. Testsuite ausführen und offene Fehler beheben (`/run-tests`).")
            lines.append("2. Fehlende REST-/WebSocket-Endpunkte und Validierungen komplettieren.")
        else:
            lines.append("1. Anwendung lokal per Docker oder Uvicorn starten (`/deploy`).")
            lines.append("2. Nächstes Feature im Frontend oder Backend implementieren.")

    return "\n".join(lines) + "\n"


def save_project_checkpoint(
    project_dir: str,
    task_summary: str = "",
    verification_ok: bool = False,
    budget_aborted: bool = False,
    cancelled: bool = False,
    files_written_count: int = 0,
    files_written: list[str] | None = None,
    next_steps: list[str] | None = None,
    verification_summary: str = "",
    clarification_questions: list[str] | None = None,
    lint_signature: list[str] | None = None,
    provider_exhausted: bool = False,
    verification_outcome: dict | None = None,
    run_stamp: str | None = None,
) -> None:
    """Speichert sowohl .ai_team_status.json als auch die lesbare PROJECT_STATE.md im Projektordner.

    `provider_exhausted=True` (zusammen mit `budget_aborted=True`) markiert einen Lauf, den der
    Fast Circuit Breaker (agents/orchestrator/department.py, PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT)
    abgebrochen hat, weil KEIN konfigurierter Provider mehr Kapazität/Guthaben hatte - im
    Unterschied zu einem generischen Lauf-Budget-Abbruch (MAX_RUN_TOKENS) ist das Projekt dann
    typischerweise unvollständig (verwaiste Teil-Artefakte) und muss vor dem nächsten Lauf
    bewusst bereinigt oder fortgesetzt werden (siehe status="aborted_due_to_quota" unten)."""
    # 1. Update .ai_team_status.json
    record_run(
        project_dir=project_dir,
        task_summary=task_summary,
        verification_ok=verification_ok,
        budget_aborted=budget_aborted,
        files_written_count=files_written_count,
        cancelled=cancelled,
        verification_summary=verification_summary,
        clarification_questions=clarification_questions,
        lint_signature=lint_signature,
        provider_exhausted=provider_exhausted,
        verification_outcome=verification_outcome,
        run_stamp=run_stamp,
    )

    # 2. Update PROJECT_STATE.md
    state_content = generate_project_state_md(
        project_dir=project_dir,
        task_summary=task_summary,
        verification_ok=verification_ok,
        budget_aborted=budget_aborted,
        cancelled=cancelled,
        files_written=files_written,
        next_steps=next_steps,
        provider_exhausted=provider_exhausted,
    )

    try:
        _state_md_path(project_dir).write_text(state_content, encoding="utf-8")
    except OSError:
        pass


def record_run(
    project_dir: str,
    task_summary: str,
    verification_ok: bool,
    budget_aborted: bool,
    files_written_count: int,
    cancelled: bool = False,
    verification_summary: str = "",
    clarification_questions: list[str] | None = None,
    lint_signature: list[str] | None = None,
    provider_exhausted: bool = False,
    verification_outcome: dict | None = None,
    run_stamp: str | None = None,
) -> None:
    """Fügt diesen Lauf vorne in die Historie ein (neueste zuerst), gedeckelt auf
    MAX_HISTORY_ENTRIES.

    Das VOLLSTÄNDIGE Verifikationsprotokoll landet zusätzlich unter `.ai_team_runs/`
    (core/run_trace.py) - `detail_file` verweist darauf, `failed_checks` nennt die
    gescheiterten Prüfungen strukturiert."""
    history = read_status(project_dir)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "task_summary": task_summary,
        "verification_ok": verification_ok,
        "budget_aborted": budget_aborted,
        "cancelled": cancelled,
        "files_written_count": files_written_count,
    }
    # Team-Optimierung (chronos_queue-Retrospektive, 20260911): expliziter Status-String
    # zusätzlich zu den bestehenden Bool-Feldern - macht per einfachem `grep`/JSON-Filter sofort
    # auffindbar, welche Läufe wegen einer Provider-Kontingent-Erschöpfung (statt eines
    # generischen Budget-Limits) unvollständig abgebrochen wurden, ohne dass ein Aufrufer erst
    # `budget_aborted UND provider_exhausted` kombinieren muss.
    if budget_aborted and provider_exhausted:
        entry["status"] = "aborted_due_to_quota"
    if lint_signature:
        # Sortiert (nicht Erfassungsreihenfolge) - has_repeated_lint_finding() vergleicht
        # zwei Läufe als Mengen-Gleichheit, die Reihenfolge, in der ruff Funde ausgibt, ist
        # dafür irrelevant und soll einen echten Vergleich nicht durch Zufall verfälschen.
        #
        # Team-Optimierung (Retrospektive 2026-09-04): `lint_signature` enthält von
        # agents/orchestrator/verification.py EINEN Eintrag JE FUND-INSTANZ, nicht je
        # distinkter Regel/Datei-Kombination - dieselbe Regel auf mehreren Zeilen derselben
        # Datei (real beobachtet: 6x "ruff:tests/test_invoices.py:DTZ001") erzeugte bisher
        # 6 identische Einträge. Ohne vorherige Deduplizierung konnte das den
        # MAX_LINT_SIGNATURE_ITEMS-Schnitt dominieren und andere, distinkte Funde verdrängen -
        # jetzt wird zuerst dedupliziert, dann sortiert/geschnitten.
        entry["lint_signature"] = sorted(set(lint_signature))[:MAX_LINT_SIGNATURE_ITEMS]
    if verification_summary.strip():
        # Bei Fehlschlag als failure_detail (siehe format_context_for_agents-Eskalation unten),
        # bei Erfolg als success_detail - Punkt 5 einer Team-Retrospektive: bisher wurde ein
        # verification_summary NUR bei Fehlschlag gespeichert. Für spätere Regressionsanalyse
        # ("lief der letzte grüne Lauf wirklich durch Lint/SAST/Coverage/Smoke, oder nur durch
        # nackte Tests?") fehlte dieselbe Information beim Erfolgsfall komplett.
        key = "failure_detail" if not verification_ok else "success_detail"
        entry[key] = truncate_on_line_boundary(verification_summary.strip(), MAX_FAILURE_DETAIL_CHARS)
        detail_file = write_verification_protocol(project_dir, verification_summary, verification_outcome, stamp=run_stamp)
        if detail_file:
            entry["detail_file"] = detail_file
    if verification_outcome:
        entry["failed_checks"] = list(verification_outcome.get("failed") or [])
    # Realer Fund: ask_human_for_clarification-Rückfragen (core/agent_toolbox.py) wurden bisher
    # NUR im Chat-Verlauf der jeweiligen Sitzung sichtbar, nie in der projektübergreifenden
    # Historie - ein späterer Lauf (ggf. andere Sitzung) wusste nichts von einer offenen Frage
    # und wiederholte denselben Rateversuch, statt sie erneut zu stellen oder gezielt
    # aufzugreifen. Wie failure_detail gedeckelt (max. 3 Fragen, je auf MAX_FAILURE_DETAIL_CHARS).
    if clarification_questions:
        entry["open_questions"] = [q.strip()[:MAX_FAILURE_DETAIL_CHARS] for q in clarification_questions if q.strip()][:3]

    # Full-Log ERST mit dem ungekürzten verification_summary befüllen (bevor entry unten
    # gekappt in .ai_team_status.json landet) - so bleibt für tiefe Fehleranalyse auch der
    # Teil erhalten, der über MAX_FAILURE_DETAIL_CHARS hinausgeht.
    full_entry = dict(entry)
    if verification_summary.strip():
        full_entry["failure_detail" if not verification_ok else "success_detail"] = verification_summary.strip()
    _append_full_log(project_dir, full_entry)

    history.insert(0, entry)
    history = history[:MAX_HISTORY_ENTRIES]
    try:
        _status_path(project_dir).write_text(
            json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8",
        )
    except OSError:
        pass


def truncate_on_line_boundary(text: str, max_chars: int) -> str:
    """Kürzt auf höchstens `max_chars`, aber nur an Zeilengrenzen - ein mitten im Wort
    abgeschnittenes Protokoll ("zurückgespielt an backend z") ist für Agenten wertlos."""
    if len(text) <= max_chars:
        return text
    marker = "\n… (gekürzt, vollständig in detail_file)"
    budget = max(0, max_chars - len(marker))
    cut = text.rfind("\n", 0, budget)
    head = text[:cut] if cut > 0 else text[:budget]
    return head.rstrip() + marker


def read_full_detail(project_dir: str, entry: dict | None) -> str:
    """Vollständiges Verifikationsprotokoll eines Status-Eintrags (Fallback: gekürzter Text)."""
    if not entry:
        return ""
    full = read_run_artifact(project_dir, str(entry.get("detail_file") or ""))
    return full or str(entry.get("failure_detail") or entry.get("success_detail") or "")


def count_consecutive_failed_runs(project_dir: str) -> int:
    """
    Zählt, wie viele der ZULETZT protokollierten Läufe (neueste zuerst) OHNE Unterbrechung
    `verification_ok=False` waren - Grundlage für eine deutlichere Warnung in
    agents/orchestrator.py, wenn dieselbe Aufgabe wiederholt an derselben Hürde scheitert,
    statt nur informativ auf `/load` hinzuweisen.

    Ein manuell abgebrochener Lauf (`cancelled=True`) zählt NICHT als Fehlschlag und
    UNTERBRICHT die Zählung - ein bewusster menschlicher Stopp sagt nichts über die
    Qualität der Aufgabe/des Agenten-Teams aus, im Unterschied zu einer nicht bestandenen
    Verifikation oder einem erreichten Budget.
    """
    count = 0
    for entry in read_status(project_dir):
        if entry.get("cancelled"):
            break
        if entry.get("verification_ok"):
            break
        count += 1
    return count


def format_context_for_agents(project_dir: str, max_entries: int = 3) -> str:
    """
    Formatiert den aktuellen Projekt-Checkpoint (PROJECT_STATE.md) sowie die letzten Läufe
    als kompakten, token-effizienten Kontext-Block für die Aufgabenbeschreibung der Agenten.
    """
    sections = []
    state_md = read_project_state_md(project_dir)
    if state_md:
        sections.append(f"## 📌 Aktueller Projekt-Checkpoint (`{STATE_MD_FILENAME}`):\n{state_md}")

    history = read_status(project_dir)[:max_entries]
    if history:
        lines = ["## 📜 Bisherige Läufe an diesem Projekt (neueste zuerst):"]
        for entry in history:
            if entry.get("verification_ok"):
                status_icon = "✅"
            elif entry.get("cancelled"):
                status_icon = "⏹️"
            elif entry.get("budget_aborted"):
                status_icon = "🚫"
            else:
                status_icon = "⚠️"
            lines.append(f"- {status_icon} [{entry.get('timestamp', '?')}] {entry.get('task_summary', '?')}")
        sections.append("\n".join(lines))

        # Realer Fund: ein Projekt (api_health_monitor) scheiterte 4 Läufe in Folge an
        # verwandten Ursachen, u.a. weil jeder neue Lauf blind erneut das komplette Feature
        # anging statt gezielt den zuvor protokollierten Fehler zu beheben - das verbrauchte
        # wiederholt Budget, ohne die eigentliche Ursache zu schließen (siehe
        # memory/diagnosing-verification-failures.md). Sind die letzten beiden Läufe BEIDE
        # nicht verifiziert, wird die konkrete Fehlermeldung des jüngsten fehlgeschlagenen
        # Laufs explizit vorangestellt statt nur der Status-Icon-Liste - macht "wiederhole
        # nicht denselben Fehler" konkret statt generisch.
        if has_repeated_failure(project_dir):
            last_detail = next((e.get("failure_detail") for e in history if e.get("failure_detail")), "")
            escalation = (
                "⚠️ **Wiederholtes Scheitern:** Die letzten 2 Läufe an diesem Projekt waren BEIDE nicht "
                "verifiziert. Starte NICHT einfach einen weiteren vollständigen Versuch - lies zuerst den "
                "konkreten Fehler des letzten Laufs unten und behebe GEZIELT diese Ursache, bevor du "
                "irgendetwas anderes am Projekt änderst."
            )
            if last_detail:
                escalation += f"\n\nLetzter konkreter Fehler:\n```\n{last_detail}\n```"
            sections.append(escalation)

        # Anders als die "wiederholtes Scheitern"-Eskalation oben (erst nach 2 Fehlschlägen in
        # Folge) wird eine offene Rückfrage schon nach dem EINEN Lauf angezeigt, der sie
        # aufgeworfen hat - eine ungeklärte, für die Aufgabe entscheidende Unklarheit blockiert
        # sofort sinnvolle Weiterarbeit, nicht erst nach einer Wiederholung.
        last_open_questions = history[0].get("open_questions") if history else None
        if last_open_questions:
            questions_text = "\n".join(f"- {q}" for q in last_open_questions)
            sections.append(
                "❓ **Offene Rückfrage(n) aus dem letzten Lauf:** Ein vorheriger Agent hat diese Fragen "
                f"als entscheidend markiert, aber noch keine Antwort erhalten:\n{questions_text}\n\n"
                "Kläre sie (per erneutem `ask_human_for_clarification` oder, falls inzwischen eindeutig "
                "beantwortbar, direkt in deiner Umsetzung), statt sie stillschweigend zu ignorieren."
            )

    return "\n\n".join(sections)


def has_open_blocker_ticket(project_dir: str, verification_ok: bool = False) -> bool:
    """Öffentlicher Wrapper um _open_blocker_ticket() für Aufrufer außerhalb dieses Moduls
    (agents/orchestrator/__init__.py nutzt dies, um den allerletzten Lauf-Status im Chat
    ebenfalls konsistent mit dem PROJECT_STATE.md-Badge zu halten, statt "✅ Fertig!" trotz
    eines offenen kritischen Befunds anzuzeigen). `verification_ok` durchreichen, wenn die
    Testsuite dieses Laufs bestanden hat - ermöglicht dieselbe automatische Ticket-Schließung
    per statischem Vollständigkeits-Check wie generate_project_state_md() oben."""
    return _open_blocker_ticket(project_dir, verification_ok=verification_ok) is not None


def has_repeated_failure(project_dir: str, streak: int = 2) -> bool:
    """True, wenn die letzten `streak` Läufe an diesem Projekt ALLE nicht verifiziert waren -
    dasselbe Kriterium, das format_context_for_agents() für die Eskalations-Warnung nutzt,
    hier auch für agents/orchestrator.py nutzbar, um vor einem weiteren vollen Lauf ein
    härteres Gate zu ziehen (siehe _run_governance_fix_loop dort), statt sich allein auf den
    Prompt-Text zu verlassen.

    Bugfix (Ultrareview-Fund): ein manuell abgebrochener (Strg+C) oder per Budget gestoppter
    Lauf setzt ebenfalls verification_ok=False, ist aber KEIN echter, gescheiterter
    Lösungsversuch - der Mensch hat den Lauf bewusst beendet, nicht das Team versagt. Ohne
    diesen Ausschluss hätten z.B. zwei aufeinanderfolgende Strg+C-Abbrüche fälschlich als
    "wiederholtes Scheitern" gegolten und ein Backlog-Ticket für einen erfundenen Fehler
    eröffnet (siehe die entsprechende Prüfung in agents/orchestrator.py)."""
    recent = read_status(project_dir)[:streak]
    return len(recent) == streak and all(
        not e.get("verification_ok") and not e.get("budget_aborted") and not e.get("cancelled")
        for e in recent
    )


def has_repeated_lint_finding(project_dir: str, streak: int = 2) -> bool:
    """True, wenn die letzten `streak` Läufe ALLE denselben, nicht-leeren Satz an Lint-Fund-
    Signaturen ("tool:datei:regel") aufweisen - unabhängig von verification_ok, budget_aborted
    oder cancelled, denn ein Lint-Fund ist bewusst rein informativ (siehe core/verifier/lint.py)
    und beeinflusst diese Felder NIE. has_repeated_failure() oben griff deshalb nie, egal wie
    oft sich derselbe Lint-Fund wiederholte (real beobachtet: omnichat, dasselbe ruff-F841 über
    drei volle Läufe unverändert). `ruff check --fix` behebt inzwischen triviale Fälle bereits
    vor dem Report (core/verifier/lint.py) - dieser Check fängt die verbleibenden, nicht
    automatisch behebbaren Funde ab, die sonst weiterhin unbegrenzt wiederkehren könnten."""
    recent = read_status(project_dir)[:streak]
    if len(recent) != streak:
        return False
    first_signature = recent[0].get("lint_signature")
    if not first_signature:
        return False
    first_set = set(first_signature)
    return all(set(e.get("lint_signature") or []) == first_set for e in recent[1:])


