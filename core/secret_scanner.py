"""
core/secret_scanner.py – Secret-Scan vor Commit/Push

Realer Fund: agents/github_agent.py committet/pusht bisher ungeprüft, was `git add -A`
staged. Schreibt ein Agent versehentlich einen echten API-Key, ein Passwort oder einen
Private Key in eine generierte Datei (z. B. eine Beispiel-`.env`, eine Konfigurationsdatei,
ein Test-Fixture), landet dieser Secret unbemerkt auf einem – möglicherweise öffentlichen –
GitHub-Repo. Dieselbe Prüf-Philosophie wie `core/code_sandbox.py`
(`_SENSITIVE_ENV_NAME_PATTERN`, Secrets vor Subprozessen verbergen), nur für den
umgekehrten Fall: Secrets vor dem eigenen Commit/Push erkennen, BEVOR sie das Repo
verlassen.

Bewusst regelbasiert (keine Netzwerkabfrage, kein LLM-Aufruf) – schnell, deterministisch,
funktioniert ohne API-Key. Erkennt bekannte Provider-Key-Formate (AWS, Google, GitHub,
Slack, Stripe, OpenAI/Anthropic-artige Tokens, private PEM-Keys) sowie generische
`key/secret/token/password = "..."`-Zuweisungen. Offensichtliche Platzhalter
(`"changeme"`, `"your-api-key-here"`, Doku-Beispielwerte wie AWS' eigenes
`AKIAIOSFODNN7EXAMPLE`) werden bewusst NICHT gemeldet, um die Warnung glaubwürdig zu halten
– ein Team, das bei jedem Platzhalter Alarm schlägt, wird beim echten Fund ignoriert.
"""

import re
from dataclasses import dataclass


@dataclass
class SecretFinding:
    """Ein einzelner, in einem Diff gefundener möglicher Secret."""
    file_path: str
    line_number: int
    rule: str
    snippet: str  # geschwärzt/gekürzt – nie der volle Secret-Wert im Klartext


# Bekannte Provider-Key-Formate: hohe Präzision, praktisch keine Fehlalarme, da diese
# Formate sich strukturell nicht mit gewöhnlichem Code/Prosa überschneiden.
_KNOWN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Google API Key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,255}")),
    ("Slack Token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("Stripe Live-Key", re.compile(r"sk_live_[0-9A-Za-z]{24,}")),
    ("Anthropic API-Key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("OpenAI-artiger Key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Private-Key-Block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
]

# Generische Zuweisung: name = "wert" / name: "wert" / name=wert (unquoted, klassisches
# .env-Format), wo der Name nach einem Secret aussieht UND der Wert lang genug ist, um kein
# einzelnes Wort/Kürzel zu sein.
#
# Bugfix (Code-Review-Fund): das vorherige \b vor der Alternation matcht NICHT zwischen '_'
# und einem Buchstaben, da beide \w sind - "DATABASE_PASSWORD"/"AWS_SECRET_ACCESS_KEY"/
# "STRIPE_SECRET_KEY" wurden dadurch NIE erkannt, obwohl genau dieses Präfix-Muster (Name des
# Diensts/der Komponente + "_" + Secret-Art) die in der Praxis häufigste Variablenbenennung
# für Secrets ist - deutlich häufiger als der bloße, unpräfigierte Name. Das führende \b ist
# jetzt entfernt (die Keyword-Liste ist spezifisch genug - z.B. "api_key", nicht nur "key" -,
# um dadurch keine neuen Fehlalarme auf unrelated Wörtern zu erzeugen).
#
# Zusätzlich erkennt die zweite Alternative jetzt auch UNGEQUOTETE Werte (`KEY=wert` ohne
# Anführungszeichen, begrenzt durch Whitespace/Kommentar/Zeilenende) - das native .env-Format,
# das dieses Modul laut eigenem Docstring oben explizit als Risiko-Beispiel nennt, wurde vorher
# NIE erkannt, weil die generische Regel zwingend Anführungszeichen verlangte.
#
# Zusätzlicher Bugfix: "secret"/"token" ALLEINSTEHEND fehlten bisher komplett - nur die
# Verbindungen "secret_key"/"access_token"/"auth_token" waren gelistet. Reale, sehr verbreitete
# Variablennamen wie STRIPE_SECRET, CLIENT_SECRET, APP_SECRET, CSRF_TOKEN oder REFRESH_TOKEN
# (ohne "_KEY"-Suffix) wurden dadurch NIE erkannt. "key" bleibt bewusst NUR in Verbindung mit
# "api" gelistet (bloßes "key" allein wäre zu generisch - primary_key, sort_key, cache_key,
# dict.keys() usw. - und würde die Warnung mit Fehlalarmen entwerten).
_GENERIC_ASSIGNMENT = re.compile(
    r"""(?i)(?:api[_-]?key|secret|token|password|passwd)[a-z0-9_]*
        \s*[:=]\s*
        (?:['"]([A-Za-z0-9_\-/+=]{12,})['"]|([A-Za-z0-9_\-/+=]{12,})(?=\s|\#|$))""",
    re.VERBOSE,
)

# Doku-/Beispielwerte, die absichtlich wie Secrets aussehen, aber keine sind – u. a. AWS'
# eigener offizieller Beispiel-Key (AKIAIOSFODNN7EXAMPLE) taucht real in Dokumentation auf.
_PLACEHOLDER_VALUE = re.compile(
    r"(?i)^(changeme|change_me|your[_-]?api[_-]?key|xxx+|placeholder|example|dummy|"
    r"fake|todo|<[^>]+>|\$\{.*\}|\.\.\.).*",
)


def _is_placeholder(line: str, value: str) -> bool:
    """True, wenn Wert oder umgebende Zeile erkennbar ein Platzhalter/Doku-Beispiel ist."""
    return bool(_PLACEHOLDER_VALUE.match(value.strip())) or "example" in line.lower()


def _redact(content: str) -> str:
    """Kürzt/zensiert eine Zeile für die Anzeige – nie der volle Secret-Wert im Terminal/Log."""
    stripped = content.strip()
    stripped = re.sub(r"""['"][A-Za-z0-9_\-/+=]{6,}['"]""", '"***REDACTED***"', stripped)
    # Bugfix (Code-Review-Fund): ungequotete Werte (natives .env-Format `KEY=wert`, seit dem
    # Fix oben von _GENERIC_ASSIGNMENT ebenfalls erkannt) wurden hier NICHT zensiert - die
    # obige Ersetzung greift nur bei Anführungszeichen. Ohne diese Zeile hätte ein neu
    # erkannter unquoted-Fund den echten Geheimwert unredigiert im Terminal/Log gezeigt,
    # obwohl genau das die dokumentierte Zusicherung dieser Funktion ist.
    stripped = re.sub(r"""([:=]\s*)[A-Za-z0-9_\-/+=]{6,}(?=\s|#|$)""", r"\1***REDACTED***", stripped)
    if len(stripped) > 80:
        stripped = stripped[:77] + "…"
    return stripped


def _scan_line(file_path: str, line_number: int, content: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for rule_name, pattern in _KNOWN_PATTERNS:
        match = pattern.search(content)
        if match and "example" not in content.lower():
            findings.append(SecretFinding(file_path, line_number, rule_name, _redact(content)))
    generic_match = _GENERIC_ASSIGNMENT.search(content)
    if generic_match:
        generic_value = generic_match.group(1) or generic_match.group(2)
        if not _is_placeholder(content, generic_value):
            findings.append(SecretFinding(file_path, line_number, "Generisches Secret-Muster", _redact(content)))
    return findings


def scan_diff(diff_text: str) -> list[SecretFinding]:
    """
    Durchsucht eine `git diff`-Ausgabe nach neu HINZUGEFÜGTEN Zeilen (`+`-Präfix, ohne den
    `+++`-Dateikopf) auf mögliche Secrets. Nur neue Zeilen zählen: ein bereits committeter
    oder gerade entfernter Secret gehört zur Historie und lässt sich durch DIESEN Push nicht
    mehr verhindern – hier geht es ausschließlich darum, was gerade neu ins Repo wandert.
    """
    findings: list[SecretFinding] = []
    current_file = "?"
    line_no = 0

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ "):
            path = raw_line[4:].strip()
            current_file = path[2:] if path.startswith("b/") else path
            continue
        if raw_line.startswith("@@"):
            match = re.search(r"\+(\d+)", raw_line)
            line_no = int(match.group(1)) - 1 if match else 0
            continue
        if raw_line.startswith("+++") or raw_line.startswith("---"):
            continue
        if raw_line.startswith("+"):
            line_no += 1
            findings.extend(_scan_line(current_file, line_no, raw_line[1:]))
        elif raw_line.startswith("-"):
            continue  # entfernte Zeilen zählen nicht in die Zeilennummerierung des neuen Stands
        else:
            line_no += 1

    return findings


# Verzeichnisse ohne eigenen Projektcode bzw. mit bewusst unechten Werten (Test-Fixtures).
_SCAN_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", ".ai_team_venv", "node_modules", "__pycache__", "dist", "build",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov", "tests", "test", "__tests__",
    ".ai-team-worktrees", ".ai_team_rag", ".ai_team_runs",
})
_SCAN_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".go", ".rs", ".java", ".kt", ".rb", ".php", ".sh", ".ps1", ".html", ".vue", ".md",
})
# Lokale, per Konvention nicht versionierte Dateien bzw. reine Vorlagen.
_SCAN_SKIP_FILES = frozenset({".env", ".env.local", ".env.example", ".env.sample", ".env.template"})
_SCAN_MAX_FILE_BYTES = 512_000


def scan_directory(root, max_files: int = 2000) -> list[SecretFinding]:
    """Durchsucht den aktuellen Dateistand eines Projekts nach möglichen Secrets.

    Ergänzt `scan_diff()` für die Definition of Done: dort zählt nicht nur der nächste Push,
    sondern ob das ausgelieferte Projekt überhaupt Secrets im Quelltext enthält. Testordner und
    lokale `.env`-Dateien sind bewusst ausgenommen (Fixtures bzw. nicht versioniert).
    """
    from pathlib import Path

    base = Path(root)
    findings: list[SecretFinding] = []
    if not base.is_dir():
        return findings
    scanned = 0
    for path in sorted(base.rglob("*")):
        if scanned >= max_files:
            break
        rel_parts = path.relative_to(base).parts
        if any(part in _SCAN_SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if not path.is_file() or path.name in _SCAN_SKIP_FILES or path.suffix.lower() not in _SCAN_EXTENSIONS:
            continue
        if path.name.startswith(".ai_team_") or path.name in ("package-lock.json", "poetry.lock"):
            continue
        try:
            if path.stat().st_size > _SCAN_MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        rel = "/".join(rel_parts)
        for line_number, line in enumerate(text.splitlines(), start=1):
            findings.extend(_scan_line(rel, line_number, line))
    return findings
