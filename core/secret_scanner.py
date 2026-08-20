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

# Generische Zuweisung: name = "wert" / name: "wert", wo der Name nach einem Secret
# aussieht UND der Wert lang genug ist, um kein einzelnes Wort/Kürzel zu sein.
_GENERIC_ASSIGNMENT = re.compile(
    r"""(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)\b
        \s*[:=]\s*
        ['"]([A-Za-z0-9_\-/+=]{12,})['"]""",
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
    if generic_match and not _is_placeholder(content, generic_match.group(2)):
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
