"""
core/team_board.py – Gemeinsames Team-Board: wie sich Agenten gegenseitig informieren

Analyse 2026-09-15: Agenten sahen voneinander nur den Dateibaum und 3000 Zeichen gekürzten
Ergebnistext. Folgen in echten Läufen: drei Rollen schrieben nacheinander `app/__init__.py`, der
tester überschrieb `app/main.py`, der security-Agent re-exportierte Symbole aus einem Modul, das
noch niemand angelegt hatte.

Das Board (`<projekt>/.ai_team_runs/team_board.json`) hält pro Lauf strukturiert fest:
- **handoffs**: Übergabe-Notiz je Agent (Dateien, `provides`, `requires`, `open_issues`)
- **claims**: wer eine Datei zuerst geschrieben hat (Owner) – Änderungen durch andere Rollen
  werden als `foreign_changes` sichtbar gemacht statt still überschrieben
- **questions**: Fragen zwischen Agenten (`ask_teammate`) samt Antwort

`format_for_agent()` liefert jedem Agenten beim Start eine kompakte, aktuelle Sicht darauf.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BOARD_REL_PATH = ".ai_team_runs/team_board.json"
MAX_LIST_ITEMS = 12
MAX_ITEM_CHARS = 240
DEFAULT_PROMPT_CHARS = 3500

_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve()).lower()
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clip_list(values, limit: int = MAX_LIST_ITEMS) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = " ".join(str(value).split())[:MAX_ITEM_CHARS]
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


@dataclass
class Handoff:
    agent_id: str
    task_id: str = ""
    files: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    open_issues: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=_now)


@dataclass
class TeammateQuestion:
    asker: str
    target: str
    question: str
    answer: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class BoardState:
    run_id: str = ""
    handoffs: list[Handoff] = field(default_factory=list)
    claims: dict[str, str] = field(default_factory=dict)
    foreign_changes: list[dict] = field(default_factory=list)
    questions: list[TeammateQuestion] = field(default_factory=list)


def board_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / BOARD_REL_PATH


def load_board(project_dir: str | Path) -> BoardState:
    path = board_path(project_dir)
    if not path.is_file():
        return BoardState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Team-Board %s nicht lesbar, starte leer: %r", path, e)
        return BoardState()
    try:
        return BoardState(
            run_id=str(raw.get("run_id", "")),
            handoffs=[Handoff(**h) for h in raw.get("handoffs", []) if isinstance(h, dict)],
            claims={str(k): str(v) for k, v in (raw.get("claims") or {}).items()},
            foreign_changes=[c for c in raw.get("foreign_changes", []) if isinstance(c, dict)],
            questions=[TeammateQuestion(**q) for q in raw.get("questions", []) if isinstance(q, dict)],
        )
    except TypeError as e:
        logger.warning("Team-Board %s hat ein unbekanntes Format, starte leer: %r", path, e)
        return BoardState()


def _save_board(project_dir: str | Path, state: BoardState) -> None:
    path = board_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("Team-Board %s konnte nicht gespeichert werden: %r", path, e)


def _update(project_dir: str | Path, mutate: Callable[[BoardState], object]):
    with _lock_for(Path(project_dir)):
        state = load_board(project_dir)
        result = mutate(state)
        _save_board(project_dir, state)
        return result


def begin_run(project_dir: str | Path, run_id: str) -> None:
    """Startet ein frisches Board für einen neuen Lauf (alte Übergaben gehören zum alten Stand)."""
    if not Path(project_dir).is_dir():
        return

    def mutate(state: BoardState) -> None:
        state.run_id = run_id
        state.handoffs.clear()
        state.claims.clear()
        state.foreign_changes.clear()
        state.questions.clear()

    _update(project_dir, mutate)


def _normalize_rel(rel_path: str) -> str:
    rel = rel_path.replace("\\", "/").strip("/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def claim_file(project_dir: str | Path, rel_path: str, agent_id: str) -> str | None:
    """Registriert den ersten Schreiber als Owner. Liefert den bisherigen Owner, falls es ein anderer ist."""
    rel = _normalize_rel(rel_path)
    if not rel or rel.startswith(".ai_team_runs/"):
        return None

    def mutate(state: BoardState) -> str | None:
        owner = state.claims.get(rel)
        if owner is None:
            state.claims[rel] = agent_id
            return None
        if owner == agent_id:
            return None
        state.foreign_changes.append({"path": rel, "owner": owner, "changed_by": agent_id, "timestamp": _now()})
        state.foreign_changes[:] = state.foreign_changes[-40:]
        return owner

    return _update(project_dir, mutate)


def record_handoff(project_dir: str | Path, handoff: Handoff) -> None:
    handoff.files = _clip_list(handoff.files, 40)
    handoff.provides = _clip_list(handoff.provides)
    handoff.requires = _clip_list(handoff.requires)
    handoff.open_issues = _clip_list(handoff.open_issues)

    def mutate(state: BoardState) -> None:
        state.handoffs.append(handoff)
        state.handoffs[:] = state.handoffs[-60:]

    _update(project_dir, mutate)


def record_question(project_dir: str | Path, question: TeammateQuestion) -> None:
    def mutate(state: BoardState) -> None:
        state.questions.append(question)
        state.questions[:] = state.questions[-40:]

    _update(project_dir, mutate)


def count_questions(project_dir: str | Path, asker: str | None = None) -> int:
    questions = load_board(project_dir).questions
    return sum(1 for q in questions if asker is None or q.asker == asker)


# ── Übergabe-Notiz aus der Agenten-Antwort ────────────────────────────────────────────────────

_HANDOFF_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_HANDOFF_LINE_RE = re.compile(
    r"^[\s>*-]*\**(provides|requires|open_issues|liefert|benötigt|offen)\**\s*:\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_LINE_KEY_ALIASES = {"liefert": "provides", "benötigt": "requires", "offen": "open_issues"}


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"\s*;\s*", value) if part.strip()]
    return []


def parse_handoff_note(text: str) -> dict[str, list[str]] | None:
    """Liest `provides`/`requires`/`open_issues` aus einem JSON-Block oder aus Schlüsselzeilen."""
    if not text:
        return None
    for match in _HANDOFF_JSON_RE.finditer(text):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict):
            data = data.get("handoff", data)
            if not isinstance(data, dict) or not any(k in data for k in ("provides", "requires", "open_issues")):
                continue
            return {key: _as_list(data.get(key)) for key in ("provides", "requires", "open_issues")}
    found: dict[str, list[str]] = {}
    for match in _HANDOFF_LINE_RE.finditer(text):
        key = _LINE_KEY_ALIASES.get(match.group(1).lower(), match.group(1).lower())
        values = [v for v in _as_list(match.group(2)) if v.lower() not in ("-", "keine", "none", "nichts")]
        found.setdefault(key, []).extend(values)
    return found or None


def derive_provides(project_dir: str | Path, files: list[str]) -> list[str]:
    """Deterministische `provides`-Einträge aus den geschriebenen Dateien (Top-Level-Symbole, Routen)."""
    base = Path(project_dir)
    provides: list[str] = []
    for rel in sorted(files):
        path = base / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        names = [
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")
        ]
        names += [
            t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name) and not t.id.startswith("_")
        ]
        routes = sorted(set(re.findall(
            r"@\w+\.(get|post|put|patch|delete|websocket)\(\s*[\"']([^\"']+)", path.read_text(encoding="utf-8", errors="replace"),
        )))
        if names:
            provides.append(f"{rel}: {', '.join(names[:10])}")
        for method, route in routes[:10]:
            provides.append(f"{method.upper()} {route} ({rel})")
    return provides


# ── Anforderungen und Schnittstellen-Status ───────────────────────────────────────────────────

_FILE_REF_RE = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|ts|tsx|js|jsx|html|css|json|toml|ini))\b")
_ROUTE_REF_RE = re.compile(r"(?<![\w.])(/(?:api|ws|v\d)[\w/{}.-]*)")
_SYMBOL_REF_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`")
# Fallback-Regex für Nicht-Python-Projekte (TS/JS/HTML), wo kein AST-Index gebaut werden kann.
# Die optionale Gruppe `(?::[^=\n]+)?` deckt annotierte Zuweisungen mit ab: ohne sie greift
# `\bALLOWED_HOSTS\s*=` bei der idiomatischen pydantic-Settings-Form
# `ALLOWED_HOSTS: list[str] = ["*"]` NICHT, weil `: list[str]` dazwischensteht (realer Fund,
# eventforge_core 2026-09-19, siehe unmet_requirements()).
_SCAN_SKIP_DIRS = frozenset({".venv", "venv", ".ai_team_venv", "node_modules", ".git", "__pycache__", "dist", "build", ".ai_team_runs"})

# Fallback, falls DEPARTMENT_DEFINITIONS nicht importierbar ist (siehe _known_role_ids()).
_FALLBACK_ROLE_IDS: frozenset[str] = frozenset({
    "product_owner", "business_analyst", "web_research", "architect", "finops", "team_lead",
    "ui_ux", "image_generator", "copywriter",
    "frontend", "backend", "database", "api_integration", "data_engineer", "mobile", "ml",
    "performance", "prompt_engineer",
    "accessibility", "i18n", "documentation", "readme",
    "devops", "tester", "security", "resilience_guard", "github",
    "code_reviewer", "refactoring", "compliance", "project_cleaner", "agent_trainer",
    "retrospective",
    "planning_lead", "design_lead", "dev_lead", "content_lead", "qa_lead", "governance_lead",
})

_known_role_ids_cache: frozenset[str] | None = None


def _known_role_ids() -> frozenset[str]:
    """Alle bekannten Agenten-/Fachbereichs-IDs des Teams.

    Realer Fund (aegisflow/sentinedge/eventforge_core, 2026-09-19): `_SYMBOL_REF_RE` hält JEDES
    in Backticks gesetzte Wort für ein Code-Symbol, das im Projekt definiert sein muss. Der
    security-Agent formuliert seine Übergaben aber praktisch immer als "`backend` muss ..." -
    und `def backend` wird es in einem generierten Projekt nie geben. Jede so formulierte
    Anforderung galt dadurch DAUERHAFT als unerfüllt, `security_handoff` blockierte
    `verification_ok` hart, und der eine Fix-Versuch in
    agents/orchestrator/integration.py._run_security_requirements_checkpoint() konnte die
    Bedingung prinzipiell nicht erfüllen. `aegisflow` war fachlich grün (Testsuite bestanden)
    und wurde allein dadurch rot.

    Rollennamen sind Adressaten der Anforderung, keine geforderten Symbole - sie werden deshalb
    vor der Symbolprüfung herausgefiltert.

    Import bewusst lokal und mit Fallback: core/team_board.py ist ein Basis-Modul, das
    agents/base_agent.py seinerseits (lazy) importiert - ein Top-Level-Import von `agents.*`
    würde diese Schichtung umkehren.
    """
    global _known_role_ids_cache
    if _known_role_ids_cache is not None:
        return _known_role_ids_cache
    try:
        from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
        ids = set(DEPARTMENT_DEFINITIONS)
        for dept in DEPARTMENT_DEFINITIONS.values():
            ids.update(dept.get("members") or [])
        _known_role_ids_cache = frozenset(ids) | _FALLBACK_ROLE_IDS
    except Exception as e:  # noqa: BLE001 - Rollenliste ist Filter, kein Blocker
        logger.debug("DEPARTMENT_DEFINITIONS nicht ladbar, nutze Fallback-Rollenliste: %r", e)
        _known_role_ids_cache = _FALLBACK_ROLE_IDS
    return _known_role_ids_cache


def _referenced_python_symbols(project_dir: Path, max_files: int = 600) -> set[str] | None:
    """Alle Namen, die die Python-Dateien des Projekts definieren, importieren ODER benutzen.

    Ersetzt die frühere reine Regex-Suche `\\b(?:def|class)\\s+X\\b|\\bX\\s*=`, die zwei
    Fehlerklassen hatte (beide real beobachtet, 2026-09-19):

    * **Annotierte Zuweisung:** `ALLOWED_HOSTS: list[str] = ["*"]` (die idiomatische
      pydantic-Settings-Form) matchte nie, weil `: list[str]` zwischen Name und `=` steht -
      `eventforge_core` meldete drei tatsächlich vorhandene Settings-Felder als fehlend.
    * **Benutzung statt Definition:** `await conn.run_sync(Base.metadata.create_all)` in
      `tests/conftest.py` erfüllt die Anforderung "auf `run_sync` umstellen", definiert aber
      nichts - `sentinedge` meldete sie trotz Umsetzung als offen.

    Bewusst großzügig (Definition ODER Import ODER Benutzung): `unmet_requirements()` beantwortet
    laut eigenem Docstring die Frage "wird das im Projekt überhaupt referenziert?", nicht "ist es
    fachlich korrekt umgesetzt?". Ein Wert-Urteil (etwa ob `ALLOWED_HOSTS` noch `["*"]` enthält)
    kann diese Prüfung ohnehin nicht fällen - ein falsch-positives Veto ist dort schädlicher als
    ein falsch-negatives, weil es sich durch keinen Fix-Versuch auflösen lässt.

    Gibt `None` zurück, wenn das Projekt keine lesbare Python-Datei enthält (z. B. ein reines
    TS/JS-Frontend) - der Aufrufer fällt dann auf die Regex-Suche im Textindex zurück.
    """
    names: set[str] = set()
    seen_python = False
    count = 0
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in _SCAN_SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            count += 1
            if count > max_files:
                return names if seen_python else None
            try:
                source = (Path(dirpath) / filename).read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
            except (OSError, SyntaxError, ValueError):
                continue
            seen_python = True
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    # Deckt `conn.run_sync(...)` und `settings.HMAC_SECRET_KEY` ab.
                    names.add(node.attr)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                elif isinstance(node, ast.arg):
                    names.add(node.arg)
                elif isinstance(node, ast.alias):
                    names.add((node.asname or node.name).split(".")[0])
    return names if seen_python else None


def _project_text_index(project_dir: Path, max_files: int = 600) -> str:
    chunks: list[str] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in _SCAN_SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".html")):
                continue
            count += 1
            if count > max_files:
                return "\n".join(chunks)
            try:
                chunks.append((Path(dirpath) / filename).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def unmet_requirements(project_dir: str | Path) -> list[tuple[str, str]]:
    """(agent_id, Anforderung) für jede `requires`-Angabe, deren Datei/Route/Symbol im Projekt fehlt.

    Anforderungen ohne erkennbare Referenz (reiner Fließtext) gelten nicht als unerfüllt.
    Rollennamen in Backticks ("`backend` muss ...") sind Adressaten, keine geforderten Symbole,
    und werden herausgefiltert - siehe `_known_role_ids()` für den realen Fund dahinter.
    Die Symbolprüfung läuft über den AST-Index (`_referenced_python_symbols()`); nur für
    Projekte ohne lesbare Python-Datei greift die Regex-Suche im Textindex.
    """
    base = Path(project_dir)
    state = load_board(base)
    pending = [(h.agent_id, req) for h in state.handoffs for req in h.requires]
    if not pending:
        return []
    corpus = _project_text_index(base)
    known_symbols = _referenced_python_symbols(base)
    role_ids = _known_role_ids()
    unmet: list[tuple[str, str]] = []
    for agent_id, requirement in pending:
        files = _FILE_REF_RE.findall(requirement)
        routes = _ROUTE_REF_RE.findall(requirement)
        symbols = [s for s in _SYMBOL_REF_RE.findall(requirement) if s not in role_ids]
        if not (files or routes or symbols):
            continue
        missing = (
            any(not (base / f).is_file() for f in files)
            or any(route.split("{")[0].rstrip("/") not in corpus for route in routes)
            or any(not _symbol_is_referenced(s, known_symbols, corpus) for s in symbols)
        )
        if missing and (agent_id, requirement) not in unmet:
            unmet.append((agent_id, requirement))
    return unmet


def _symbol_is_referenced(symbol: str, known_symbols: set[str] | None, corpus: str) -> bool:
    """Ist `symbol` im Projekt definiert, importiert oder benutzt?

    Bevorzugt den AST-Index; ohne Python-Dateien (`known_symbols is None`) bleibt die
    Regex-Suche im Textindex - dort jetzt mit optionaler Typannotation zwischen Name und `=`,
    damit `X: list[str] = [...]` nicht länger als fehlend gilt.
    """
    if known_symbols is not None:
        return symbol in known_symbols
    escaped = re.escape(symbol)
    pattern = rf"\b(?:def|class|function|const|let|var)\s+{escaped}\b|\b{escaped}\s*(?::[^=\n]+)?="
    return bool(re.search(pattern, corpus))


def contract_status(project_dir: str | Path) -> tuple[list[str], list[str]]:
    """(umgesetzt, offen) für die Module aus `interface_contract.json`."""
    from core.failure_triage import load_interface_contract
    from core.write_guard import top_level_symbols

    base = Path(project_dir)
    implemented: list[str] = []
    planned: list[str] = []
    for module, symbols in sorted(load_interface_contract(base).items()):
        path = base / module
        defined: set[str] = set()
        if path.is_file():
            try:
                defined = top_level_symbols(path.read_text(encoding="utf-8", errors="replace")) or set()
            except OSError:
                defined = set()
        missing = [name for name in symbols if name not in defined]
        if path.is_file() and not missing:
            implemented.append(module)
        else:
            planned.append(f"{module} ({', '.join(missing[:5]) or 'Datei fehlt'})")
    return implemented, planned


# ── Sicht für den Agenten ─────────────────────────────────────────────────────────────────────

def format_for_agent(project_dir: str | Path, agent_id: str, max_chars: int = DEFAULT_PROMPT_CHARS) -> str:
    """Kompakte, aktuelle Board-Sicht für den Prompt eines Agenten (leer, wenn nichts vorliegt)."""
    base = Path(project_dir)
    if not base.is_dir():
        return ""
    state = load_board(base)
    lines: list[str] = []

    latest: dict[str, Handoff] = {}
    for handoff in state.handoffs:
        if handoff.agent_id != agent_id:
            latest[handoff.agent_id] = handoff
    if latest:
        lines.append("**Übergaben deiner Teamkollegen (aktueller Lauf):**")
        for other, handoff in latest.items():
            lines.append(f"- `{other}` – Dateien: {', '.join(handoff.files[:8]) or '–'}")
            if handoff.provides:
                lines.append(f"  - liefert: {'; '.join(handoff.provides[:6])}")
            if handoff.requires:
                lines.append(f"  - braucht: {'; '.join(handoff.requires[:4])}")
            if handoff.open_issues:
                lines.append(f"  - offen: {'; '.join(handoff.open_issues[:4])}")

    try:
        implemented, planned = contract_status(base)
    except Exception as e:  # noqa: BLE001 - Board-Sicht darf den Agenten-Start nie blockieren
        logger.warning("Schnittstellen-Status nicht ermittelbar: %r", e)
        implemented, planned = [], []
    if planned:
        lines.append(
            f"**Schnittstellen-Vertrag:** {len(implemented)} umgesetzt, {len(planned)} noch offen "
            "(NICHT importieren/re-exportieren, bevor sie existieren): " + "; ".join(planned[:8])
        )

    own_files = sorted(path for path, owner in state.claims.items() if owner == agent_id)
    foreign = [c for c in state.foreign_changes if c.get("owner") == agent_id]
    if foreign:
        lines.append("**Andere Rollen haben deine Dateien geändert – prüfe sie vor weiteren Änderungen:**")
        lines += [f"- `{c.get('path')}` geändert von `{c.get('changed_by')}`" for c in foreign[-6:]]
    others_owned = {path: owner for path, owner in state.claims.items() if owner != agent_id}
    if others_owned:
        shown = ", ".join(f"{path} ({owner})" for path, owner in list(others_owned.items())[:12])
        lines.append(f"**Datei-Owner:** {shown}. Änderungen an fremden Dateien nur gezielt und im Bericht begründen.")
    if own_files:
        lines.append(f"**Deine Dateien:** {', '.join(own_files[:12])}")

    answered = [q for q in state.questions if q.answer and agent_id in (q.asker, q.target)]
    if answered:
        lines.append("**Geklärte Fragen im Team:**")
        lines += [f"- {q.asker} → {q.target}: {q.question[:120]} ⇒ {q.answer[:200]}" for q in answered[-4:]]

    if not lines:
        return ""
    text = "## 🗂️ TEAM-BOARD\n" + "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 20].rsplit("\n", 1)[0] + "\n- … (gekürzt)"


# ── Fragen an Teamkollegen ────────────────────────────────────────────────────────────────────

TeammateResponder = Callable[[str, str, str, str], Awaitable[str]]
_responders: dict[str, TeammateResponder] = {}


def _responder_key(project_dir: str | Path) -> str:
    return str(Path(project_dir).resolve()).lower()


def register_teammate_responder(project_dir: str | Path, responder: TeammateResponder) -> None:
    """Der Orchestrator registriert pro Lauf, wie eine Frage an einen Kollegen beantwortet wird."""
    _responders[_responder_key(project_dir)] = responder


def unregister_teammate_responder(project_dir: str | Path) -> None:
    _responders.pop(_responder_key(project_dir), None)


def get_teammate_responder(project_dir: str | Path) -> TeammateResponder | None:
    return _responders.get(_responder_key(project_dir))
