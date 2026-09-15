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
_SCAN_SKIP_DIRS = frozenset({".venv", "venv", ".ai_team_venv", "node_modules", ".git", "__pycache__", "dist", "build", ".ai_team_runs"})


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
    """
    base = Path(project_dir)
    state = load_board(base)
    pending = [(h.agent_id, req) for h in state.handoffs for req in h.requires]
    if not pending:
        return []
    corpus = _project_text_index(base)
    unmet: list[tuple[str, str]] = []
    for agent_id, requirement in pending:
        files = _FILE_REF_RE.findall(requirement)
        routes = _ROUTE_REF_RE.findall(requirement)
        symbols = _SYMBOL_REF_RE.findall(requirement)
        if not (files or routes or symbols):
            continue
        missing = (
            any(not (base / f).is_file() for f in files)
            or any(route.split("{")[0].rstrip("/") not in corpus for route in routes)
            or any(not re.search(rf"\b(?:def|class)\s+{re.escape(s)}\b|\b{re.escape(s)}\s*=", corpus) for s in symbols)
        )
        if missing and (agent_id, requirement) not in unmet:
            unmet.append((agent_id, requirement))
    return unmet


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


def planned_modules(project_dir: str | Path) -> set[str]:
    """Modulpfade aus dem Vertrag, die noch nicht (vollständig) existieren."""
    return {entry.split(" (", 1)[0] for entry in contract_status(project_dir)[1]}


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
