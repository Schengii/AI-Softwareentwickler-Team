"""
core/review_gate.py – Erkennt "kritische" Befunde in Berichten der REVIEW_ONLY-Agenten
(code_reviewer/security/compliance, siehe agents/orchestrator.py.REVIEW_ONLY_AGENT_IDS) und
ordnet sie den Datei-Verantwortlichen zu.

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: alle drei Rollen kategorisieren
Befunde explizit nach Schweregrad (code_reviewer: feste Überschrift "### 🔴 Kritische Probleme
(müssen behoben werden)"; security: "Schweregrad-Bewertung (Kritisch/Hoch/Mittel/Niedrig/Info)";
compliance: 🔴-markierte Risikostufe in der Lizenz-Tabelle) – aber NICHTS im Orchestrator hat
das je ausgewertet. Ein "Kritisch"-Fund landete nur im Fließtext des Endberichts, ohne dass
irgendein Agent beauftragt wurde, ihn zu beheben (anders als ein echter Testfehler, siehe
agents/orchestrator.py._run_verification_loop()). Ein echtes Team behandelt ein "Kritisch" im
Code-Review als Blocker, nicht als FYI.

Bewusst eine Text-Heuristik, KEIN vollständiger Markdown-Parser (die drei Rollen liefern drei
unterschiedliche Formate, alle frei vom LLM formuliert) – analog zu den bereits bestehenden
Heuristiken _ADR_TEXT_MARKERS (agents/base_agent.py) und _is_rate_limit_error()
(core/llm_factory.py): lieber ein pragmatischer, gut getesteter Best-Effort-Treffer auf die
tatsächlich in den System-Prompts vorgeschriebenen Formate als ein Versuch, jede denkbare
Formulierung zu erfassen.
"""

import json
import re
from dataclasses import dataclass


@dataclass
class ReviewFinding:
    """Repräsentiert einen strukturierten Review-/Governance-Befund."""
    severity: str  # "critical" | "warning" | "info"
    source_role: str = "reviewer"
    file_path: str = ""
    line_number: int | None = None
    title: str = ""
    description: str = ""
    suggested_fix: str = ""
    raw_text: str = ""


# 🔴 UND das Wort "kritisch" decken alle drei Formate ab: code_reviewer nutzt beides in seiner
# Überschrift, compliance nutzt 🔴 in der Risikostufen-Spalte, security nutzt nur das Wort
# ("Schweregrad: Kritisch"). Für Überschriften (Pass 1 unten) reicht diese lockere Fassung -
# eine Überschrift IST bereits die Kategorie-Bezeichnung selbst, kein Fließtext.
_CRITICAL_RE = re.compile(r"🔴|kritisch\w*", re.IGNORECASE)

# Strenger als _CRITICAL_RE: für Fließtext (Pass 2/3 unten), wo das bloße Wort "kritisch"
# irgendwo im Satz zu viele Fehlalarme produziert (real beobachtet: "... aber ein kritischer
# Sicherheitsfehler" in einer Gesamtbewertung ist keine Einzelfund-Meldung). Verlangt einen
# erkennbaren Schweregrad-Marker in Fund-Nähe (Label+Doppelpunkt, Fettdruck, Klammer, 🔴)
# statt nur des bloßen Wortes irgendwo im Satz.
_SEVERITY_MARKER_RE = re.compile(
    r"(schweregrad|severity|risikostufe|einstufung|kritikalität)\s*[:\-]?\s*\**\s*kritisch"
    r"|\*\*kritisch\w*\*\*"
    r"|\(kritisch\)"
    r"|kritisch\w*\s*[:\-]"
    r"|🔴",
    re.IGNORECASE,
)

# Verhindert Fehlalarme bei "keine kritischen Probleme gefunden"/"0 kritische Befunde" - ohne
# diesen Filter würde JEDER Report, der die Kategorie nur nennt, um sie als leer zu bestätigen,
# fälschlich einen Fix-Auftrag auslösen.
_NEGATIVE_RE = re.compile(
    r"keine\s+(weiteren\s+)?kritisch\w*|kritisch\w*\s*:?\s*(keine|0|-)\s*$|0\s+kritisch\w*",
    re.IGNORECASE,
)

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MIN_FINDING_CHARS = 15

_BACKTICK_PATH_RE = re.compile(r"`([^`\n]{2,150})`")
_PATH_LIKE_RE = re.compile(r"^[\w.][\w./\\-]*\.\w{1,6}$")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_real_finding(block: str) -> bool:
    """Filtert Platzhalter/"keine Befunde"-Bestätigungen und zu kurze Treffer heraus."""
    stripped = block.strip().strip("[]").strip()
    if len(stripped) < _MIN_FINDING_CHARS:
        return False
    if _NEGATIVE_RE.search(stripped):
        return False
    return True


def parse_structured_findings(content: str, source_role: str = "") -> list[ReviewFinding]:
    """
    Parst Review-Befunde sowohl aus strukturierten JSON-Codeblöcken als auch
    per Heuristik aus Freitext und formatiert sie als typisierte `ReviewFinding`-Objekte.
    """
    if not content:
        return []

    findings: list[ReviewFinding] = []

    # 1. Versuche JSON-Codeblöcke zu parsen
    json_block_match = re.search(r"```(?:json)?\s*(\[\s*\{.*?\}\s*\])\s*```", content, re.DOTALL)
    if json_block_match:
        try:
            data = json.loads(json_block_match.group(1))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        sev = (item.get("severity") or "warning").lower()
                        findings.append(ReviewFinding(
                            severity="critical" if "crit" in sev or "krit" in sev else sev,
                            source_role=source_role or item.get("source_role", "reviewer"),
                            file_path=item.get("file_path", "") or item.get("file", ""),
                            line_number=item.get("line_number") or item.get("line"),
                            title=item.get("title", ""),
                            description=item.get("description", "") or item.get("detail", ""),
                            suggested_fix=item.get("suggested_fix", "") or item.get("fix", ""),
                            raw_text=json.dumps(item, ensure_ascii=False),
                        ))
                if findings:
                    return findings
        except Exception:
            pass

    # 2. Fallback auf Text-Heuristiken
    raw_critical = find_critical_findings(content)
    findings.extend(finding_from_critical_block(block, source_role) for block in raw_critical)

    return findings


def finding_from_critical_block(block: str, source_role: str = "") -> ReviewFinding:
    """
    Wandelt EINEN rohen, bereits als kritisch erkannten Textblock (z.B. aus find_critical_
    findings()) in ein ReviewFinding um - inklusive Best-effort-Extraktion eines Dateipfads aus
    Backtick-Code (`` `app/main.py` ``). Ausgelagert aus parse_structured_findings() (Pass 2
    oben), damit auch ein Aufrufer, der bereits eine eigene Liste roher Blöcke hat (z.B. core/
    review_gate-Konsumenten mit einer bereits über mehrere Re-Review-Runden angereicherten
    still_critical-Liste), dieselbe Datei-Extraktion nutzen kann statt sie zu duplizieren.

    Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-Kommentare): genau
    dieses ReviewFinding.file_path/line_number ist die Grundlage dafür, einen unbehobenen
    kritischen Governance-Befund als ECHTEN GitHub-PR-Review-Kommentar an der betroffenen Datei
    zu hinterlassen (agents/github_agent.py.post_pr_review()), statt ihn nur als Fließtext im
    PR-Body zu verstecken.
    """
    extracted_path = ""
    for cand in _BACKTICK_PATH_RE.findall(block):
        if _PATH_LIKE_RE.match(cand.strip().replace("\\", "/")):
            extracted_path = cand.strip()
            break
    return ReviewFinding(
        severity="critical",
        source_role=source_role or "reviewer",
        file_path=extracted_path,
        title=block.splitlines()[0][:80],
        description=block,
        raw_text=block,
    )


def find_critical_findings(content: str) -> list[str]:
    """
    Extrahiert alle als "kritisch" markierten Abschnitte aus einem Review-Report. Gibt eine
    Liste roher Textblöcke zurück (leer, wenn nichts Kritisches gefunden wurde bzw. der Report
    explizit "keine kritischen Befunde" bestätigt).

    Drei unabhängige, deduplizierte Durchläufe für die drei real beobachteten Formate:
    1. Überschriften-Abschnitte (code_reviewer: "### 🔴 Kritische Probleme" bis zur nächsten
       Überschrift) - der zuverlässigste Fall, da code_reviewer dieses Format fest vorschreibt.
    2. Tabellenzeilen mit 🔴 (compliance: Risikostufen-Spalte der Lizenz-Tabelle).
    3. Freitext-Absätze mit "kritisch" (security: keine feste Überschrift, Schweregrad steht
       inline bei jedem Fund) - nur Absätze, die nicht schon durch (1) erfasst wurden.
    """
    if not content:
        return []

    findings: list[str] = []
    seen: set[str] = set()

    def _add(block: str) -> None:
        block = block.strip()
        if not block or not _is_real_finding(block):
            return
        key = _normalize(block)
        if key in seen:
            return
        seen.add(key)
        findings.append(block)

    lines = content.splitlines()

    # 1) Überschriften-Abschnitte: von einer "kritisch"-Überschrift bis zur nächsten Überschrift.
    heading_line_indices = [i for i, ln in enumerate(lines) if _HEADING_RE.match(ln)]
    covered_ranges: list[tuple[int, int]] = []
    for pos, i in enumerate(heading_line_indices):
        heading_text = _HEADING_RE.match(lines[i]).group(1)
        if not _CRITICAL_RE.search(heading_text):
            continue
        end = heading_line_indices[pos + 1] if pos + 1 < len(heading_line_indices) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        _add(f"{heading_text.strip()}\n{body}" if body else heading_text.strip())
        covered_ranges.append((i, end))

    def _covered(line_idx: int) -> bool:
        return any(start <= line_idx < end for start, end in covered_ranges)

    # 2) Tabellenzeilen mit 🔴, die nicht schon Teil eines oben erfassten Abschnitts sind.
    for i, ln in enumerate(lines):
        if _covered(i):
            continue
        if _TABLE_ROW_RE.match(ln) and _SEVERITY_MARKER_RE.search(ln):
            _add(ln)

    # 3) Freitext-Absätze (durch Leerzeilen getrennt) mit einem Schweregrad-Marker, die weder
    # Überschrift noch (vollständig aus) Tabellenzeilen bestehen und nicht schon oben erfasst
    # wurden. Ganze Tabellen werden hier bewusst übersprungen - die sind bereits zeilenweise
    # durch Pass 2 abgedeckt (sonst würde ein 🔴 in EINER Zeile die GESAMTE mehrzeilige Tabelle
    # inkl. unkritischer Zeilen als einen einzigen Fund mitreißen).
    covered_line_set = {i for start, end in covered_ranges for i in range(start, end)}
    for para in re.split(r"\n\s*\n", content):
        para_lines = [ln for ln in para.splitlines() if ln.strip()]
        # Überschriftenzeilen selbst tragen nie den Fund (der steht im nachfolgenden Text) -
        # nur die Zeile selbst ausklammern statt den ganzen Absatz zu verwerfen, falls direkt
        # nach einer Überschrift (ohne Leerzeile dazwischen) echter Inhalt folgt.
        body_lines = [ln for ln in para_lines if not _HEADING_RE.match(ln)]
        if not body_lines or all(_TABLE_ROW_RE.match(ln) for ln in body_lines):
            continue
        body_text = "\n".join(body_lines)
        if not _SEVERITY_MARKER_RE.search(body_text):
            continue
        # Bereits durch (1) erfasst, wenn der Absatz komplett innerhalb eines covered Bereichs liegt.
        para_line_no = next((i for i, ln in enumerate(lines) if ln.strip() and ln.strip() in body_text), None)
        if para_line_no is not None and para_line_no in covered_line_set:
            continue
        _add(body_text)

    return findings


# Realer Fund (Bestandsaufnahme eines echten Laufs, omnichat-Projekt): der security-Agent
# identifizierte ein echtes kritisches Problem (Pydantic-v2-Migration, CORS-Härtung), hatte in
# diesem konkreten Aufruf aber keine Schreibrechte (z.B. während einer Konsolidierungs-/
# Delegationsrunde, siehe agents/orchestrator/department.py) und griff statt zu einem Bericht
# mit "Kritisch"-Markierung (den _CRITICAL_RE/find_critical_findings oben erfassen würden) zu
# `ask_human_for_clarification` mit der Frage "Wie erhalte ich Schreibrechte...?". Diese Frage
# landete unbeantwortet in .ai_team_status.json und wurde NIE automatisch an einen
# schreibberechtigten Agenten weitergeroutet - anders als ein normaler Governance-Fund blieb
# das Problem so über beliebig viele Läufe hinweg ungelöst liegen. Dieses Muster (Fund
# vorhanden, aber "ich kann nicht schreiben/habe keine Berechtigung") wird hier erkannt, damit
# _run_permission_blocked_clarification_fix() (agents/orchestrator/verification.py) dieselbe
# Fix-Schleife wie für echte Governance-Befunde anstoßen kann, statt auf eine nie kommende
# menschliche Antwort auf eine rein technische Blockade zu warten.
_PERMISSION_BLOCKED_RE = re.compile(
    r"keine\s+schreibrechte|kann\s+(ich\s+)?(selbst\s+)?nicht\s+(schreiben|ändern|korrigieren|beheben)"
    r"|habe\s+keine\s+(schreib|bearbeitungs)berechtigung|nicht\s+autorisiert.{0,20}(schreiben|ändern)"
    r"|no\s+write\s+access|not\s+authorized\s+to\s+(write|edit|modify)|read.?only\s+access",
    re.IGNORECASE,
)


def find_permission_blocked_questions(questions: list[str]) -> list[str]:
    """
    Filtert `questions` (z.B. AgentResult.clarification_questions) auf jene, die laut
    `_PERMISSION_BLOCKED_RE` einen fehlenden Schreibzugriff als Grund für eine Rückfrage
    nennen, statt eine echte fachliche Unklarheit. Siehe Kommentar oberhalb von
    `_PERMISSION_BLOCKED_RE` für den realen Fund, der diese Funktion motiviert hat.
    """
    return [q for q in questions if q.strip() and _PERMISSION_BLOCKED_RE.search(q)]


# Realer Fund (incidentpilot-Projekt): der tester-Agent stellte die Rückfrage "Soll ich die
# Grundstruktur der Anwendung ... von Grund auf neu erstellen ...? Ich benötige Informationen,
# ob ich die Backend-Struktur selbst initialisieren soll" - eine reine Ausführungs-/Scope-Frage
# ("darf ich die fehlende Struktur selbst bauen?"), auf die es für ein autonom arbeitendes Team
# ohne anwesenden Menschen nur eine sinnvolle Antwort gibt ("ja"). Diese Frage blieb bisher
# unbeantwortet stehen, der Lauf endete ohne die eigentliche Kernfunktion.
#
# WICHTIG, bewusst als ALLOWLIST (Gegenteil von _PERMISSION_BLOCKED_RE oben) statt als "alles
# außer Schreibrechte-Fragen" umgesetzt: eine echte fachliche Unklarheit, die nur ein Mensch
# beantworten kann (z.B. "Welche Zahlungsanbieter sollen unterstützt werden?", siehe
# tests/test_clarification_escalation.py), darf NIEMALS automatisch "beantwortet" werden - das
# würde die bewusste Mid-Task-Eskalation an einen Menschen (core/agent_toolbox.py.
# ask_human_for_clarification) unterlaufen. Nur Rückfragen, die eindeutig danach fragen, ob der
# Agent selbst fehlende Struktur/Dateien anlegen darf, werden erfasst - alles andere bleibt
# unangetastet offen für einen Menschen.
# Erweiterung (Team-Retrospektive, webhookshield-Projekt): die ursprüngliche Fassung erfasste
# nur "von Grund auf neu ERSTELLEN" und eine enge Verb-Liste nach "soll ich" - drei reale
# Rückfragen in ein und demselben Lauf ("... neu AUFSETZEN?", "Können Sie die Dateien
# bereitstellen ... in welchem Verzeichnis ich arbeiten soll?", "Projektverzeichnis ist komplett
# LEER ... kann ich keine Reparatur ...") rutschten alle drei durch dieses engere Muster und
# blieben unbeantwortet liegen, obwohl sie inhaltlich dieselbe Klasse Frage sind ("es existiert
# kein Code - darf ich ihn selbst anlegen?"). Ergänzt um weitere Verben (aufsetzen, aufbauen,
# reparieren, wiederherstellen, bereitstellen) und einen zweiten Zweig, der direkt auf die
# Feststellung "Verzeichnis/Ordner ist leer/nicht vorhanden" abzielt, unabhängig vom Verb danach
# - bleibt bewusst weiterhin eine ALLOWLIST (siehe Docstring unten), kein "alles außer
# Schreibrechte-Fragen".
_STRUCTURAL_SCOPE_RE = re.compile(
    r"von\s+grund\s+auf\s+neu\s+(erstellen|aufsetzen|aufbauen|initialisieren)"
    r"|soll\s+ich.{0,80}(selbst\s+)?(anlegen|erstellen|initialisieren|aufbauen|aufsetzen|reparieren)"
    r"|grundstruktur.{0,60}(erstellen|anlegen|aufbauen|initialisieren|aufsetzen)"
    r"|(projekt(verzeichnis)?|ordner|verzeichnis).{0,40}(ist|sind)?.{0,10}(komplett\s+)?leer"
    r"|kein(e)?\s+(bestehende|vorhandene)?\s*(codebasis|app.?verzeichnis|projektstruktur)"
    r"|(dateien|code)\s+(bereitstellen|zur\s+verf[üu]gung\s+stellen)"
    r"|neues?\s+projekt\s+von\s+grund\s+auf\s+neu\s+aufsetzen",
    re.IGNORECASE,
)


def find_structural_scope_questions(questions: list[str]) -> list[str]:
    """
    Filtert `questions` auf jene, die laut `_STRUCTURAL_SCOPE_RE` eindeutig danach fragen, ob
    der Agent selbst fehlende Grundstruktur/Dateien anlegen darf - NICHT auf jede Rückfrage, die
    keine Schreibrechte-Frage ist (siehe Kommentar oberhalb von `_STRUCTURAL_SCOPE_RE` für den
    Sicherheitsgrund dieser bewussten Allowlist-Enge).
    """
    return [q for q in questions if q.strip() and _STRUCTURAL_SCOPE_RE.search(q)]


# Realer Fund (pulseflow_gateway-Retrospektive, 20260911_095217): ein Governance-Befund zu
# "fehlendem Einstiegspunkt/fehlender Kern-Implementierung" zitierte in Backticks NUR bereits
# vorhandene BELEG-Dateien (README.md, requirements.txt) statt der fehlenden Zieldatei selbst -
# die reguläre Backtick-Suche unten routete den Fix dadurch an die tatsächlichen Owner DIESER
# Beleg-Dateien (readme, data_engineer), die das strukturelle Problem gar nicht lösen können.
# Das erzeugte einen 5-fachen Ping-Pong zwischen Reviewer und Compliance (400k Tokens
# verschwendet), bevor der Lauf schließlich am Budget scheiterte. Ein Befund über einen
# fehlenden Einstiegspunkt/fehlende API-Routen/fehlende Server-Datei geht deshalb IMMER
# deterministisch an backend (bzw. frontend bei einem erkennbaren UI-Befund) - unabhängig
# davon, welche Datei im Fund-Text zufällig zitiert wird.
_MISSING_ENTRYPOINT_RE = re.compile(
    r"(fehlend\w*|fehlt\w*|kein\w*|missing|\bno\b)[^.]{0,30}?"
    r"(einstiegspunkt|entry.?point|api.?route\w*|server.?datei\w*|hauptdatei|"
    r"kern.?implementierung|core.?implementation|anwendungscode|application\s+code)"
    r"|(main\.py|app\.py|run\.py)\s+(fehlt|existiert\s+nicht|wurde\s+nie\s+angelegt|is\s+missing)"
    r"|kein(e)?\s+(einzige\s+)?zeile\s+(anwendungs)?code",
    re.IGNORECASE,
)
_UI_HINT_RE = re.compile(r"frontend|\bui\b|oberfl[äa]che|react|vue|index\.html", re.IGNORECASE)


def _deterministic_entrypoint_owner(text: str) -> str | None:
    """
    Erzwingt backend (bzw. frontend bei einem UI-Befund) als Owner für Governance-Befunde über
    fehlenden Anwendungscode/Einstiegspunkt - siehe Modul-Kommentar oberhalb dieser Funktion für
    den realen Fund, der diese Vorrangregel motiviert. Gibt None zurück, wenn der Fund-Text
    keinem der bekannten Entrypoint-Muster entspricht - dann greift die reguläre, backtick-
    basierte Zuordnung in route_findings_to_owners() unverändert.
    """
    if not _MISSING_ENTRYPOINT_RE.search(text):
        return None
    return "frontend" if _UI_HINT_RE.search(text) else "backend"


def route_findings_to_owners(
    findings: list[tuple[str, str]], file_owners: dict[str, str],
) -> tuple[dict[str, list[str]], list[str]]:
    """
    `findings`: Liste aus (meldende Rolle, Fund-Text), z.B. [("code_reviewer", "### 🔴 ...")].

    Sucht in jedem Fund-Text nach Backtick-zitierten Dateipfaden und gleicht sie gegen
    `file_owners` (agents/orchestrator.py) ab - exakter Treffer oder Suffix-Übereinstimmung,
    damit sowohl ein voller relativer Pfad ("backend/db.py") als auch ein abgekürzter
    Dateiname ("db.py") funktioniert. Gibt (agents_to_fix, unrouted) zurück:
    - agents_to_fix: Owner-Agent-ID -> Liste lesbarer Fund-Beschreibungen (inkl. meldender Rolle)
    - unrouted: Fund-Texte OHNE eindeutig zuordenbaren Datei-Owner - kein stiller Verlust,
      werden vom Aufrufer (agents/orchestrator.py._run_governance_fix_loop) als "braucht
      manuelle Prüfung" protokolliert statt verworfen.

    Ein Befund über einen fehlenden Einstiegspunkt/fehlende Kern-Implementierung wird VOR der
    Backtick-Suche deterministisch an backend/frontend geroutet (siehe
    `_deterministic_entrypoint_owner`) - niemals an readme oder einen anderen Doku-/Daten-Agenten.
    """
    agents_to_fix: dict[str, list[str]] = {}
    unrouted: list[str] = []

    for source_role, text in findings:
        owner = _deterministic_entrypoint_owner(text)
        for candidate in [] if owner else _BACKTICK_PATH_RE.findall(text):
            candidate = candidate.strip().replace("\\", "/")
            if not _PATH_LIKE_RE.match(candidate):
                continue
            for owned_path, owner_id in file_owners.items():
                normalized = owned_path.replace("\\", "/")
                if normalized == candidate or normalized.endswith(f"/{candidate}") or candidate.endswith(f"/{normalized}"):
                    owner = owner_id
                    break
            if owner:
                break

        entry = f"[{source_role}] {text.strip()}"
        if owner:
            agents_to_fix.setdefault(owner, []).append(entry)
        else:
            unrouted.append(entry)

    return agents_to_fix, unrouted


def route_structured_findings(
    findings: list[ReviewFinding], file_owners: dict[str, str],
) -> tuple[dict[str, list[ReviewFinding]], list[ReviewFinding]]:
    """
    Ordnet typisierte `ReviewFinding`-Objekte anhand von `file_path` oder Backticks
    dem zuständigen Datei-Owner zu.
    """
    agents_to_fix: dict[str, list[ReviewFinding]] = {}
    unrouted: list[ReviewFinding] = []

    for finding in findings:
        owner = None
        target_path = finding.file_path.strip().replace("\\", "/")

        if target_path:
            for owned_path, owner_id in file_owners.items():
                normalized = owned_path.replace("\\", "/")
                if normalized == target_path or normalized.endswith(f"/{target_path}") or target_path.endswith(f"/{normalized}"):
                    owner = owner_id
                    break

        if not owner and finding.raw_text:
            for candidate in _BACKTICK_PATH_RE.findall(finding.raw_text):
                candidate = candidate.strip().replace("\\", "/")
                if not _PATH_LIKE_RE.match(candidate):
                    continue
                for owned_path, owner_id in file_owners.items():
                    normalized = owned_path.replace("\\", "/")
                    if normalized == candidate or normalized.endswith(f"/{candidate}") or candidate.endswith(f"/{normalized}"):
                        owner = owner_id
                        break
                if owner:
                    break

        if owner:
            agents_to_fix.setdefault(owner, []).append(finding)
        else:
            unrouted.append(finding)

    return agents_to_fix, unrouted
