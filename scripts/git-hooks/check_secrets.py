#!/usr/bin/env python3
"""
scripts/git-hooks/check_secrets.py – Pre-Commit Secret- & .env-Gate

Prüft vor jedem Git-Commit:
1. Ob echte .env-Dateien (z. B. .env, .env.local, .env.prod; außer .env.example) gestaged sind.
2. Ob der gestagte Diff (git diff --cached) echte API-Keys, Private Keys, Tokens oder
   Passwörter enthält (nutzt core/secret_scanner.py).

Gibt Exit-Code 1 zurück und blockiert den Commit, falls Verstöße gefunden werden.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Projekt-Root zu sys.path hinzufügen
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from core.secret_scanner import SecretFinding, scan_diff
except ImportError:
    # Fallback falls core nicht direkt importierbar ist
    SecretFinding = None
    scan_diff = None


def check_staged_env_files() -> list[str]:
    """Prüft, ob .env-Dateien im Git Staging-Bereich liegen."""
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        print(f"⚠️ Warnung: Git-Status konnte nicht gelesen werden: {exc}", file=sys.stderr)
        return []

    if res.returncode != 0:
        return []

    blocked_files: list[str] = []
    for line in res.stdout.splitlines():
        clean_path = line.strip().replace("\\", "/")
        if not clean_path:
            continue
        file_name = Path(clean_path).name.lower()

        # .env.example ist explizit als Vorlage erlaubt
        if file_name == ".env.example":
            continue

        # Blockiere .env, .env.*, *.env, *.env.*
        if file_name == ".env" or file_name.startswith(".env.") or file_name.endswith(".env") or ".env." in file_name:
            blocked_files.append(clean_path)

    return blocked_files


def check_staged_secrets() -> list[SecretFinding]:
    """Scannt neu hinzugefügte Zeilen im Staged-Diff nach echten API-Keys und Secrets."""
    if scan_diff is None:
        return []

    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--no-color", "--unified=0"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        print(f"⚠️ Warnung: Staged Diff konnte nicht gelesen werden: {exc}", file=sys.stderr)
        return []

    if res.returncode != 0 or not res.stdout:
        return []

    return scan_diff(res.stdout)


def main() -> int:
    """Führt alle Prüfungen aus und liefert 1 bei Verstößen, sonst 0."""
    # 1. Gate: .env-Dateien prüfen
    blocked_env = check_staged_env_files()
    if blocked_env:
        print("\n" + "=" * 76, file=sys.stderr)
        print("❌ COMMIT ABGEBROCHEN: Gestagte .env-Datei(en) entdeckt!", file=sys.stderr)
        print("=" * 76, file=sys.stderr)
        for filepath in blocked_env:
            print(f"  🛑 Blockiert: {filepath}", file=sys.stderr)
        print("\nSicherheitsregel:", file=sys.stderr)
        print("  Echte Umgebungsdateien mit API-Keys dürfen NIEMALS committet werden.", file=sys.stderr)
        print("  Entferne die Datei mit:", file=sys.stderr)
        print("    git restore --staged <datei>  (oder: git reset HEAD <datei>)", file=sys.stderr)
        print("  Nutze stattdessen .env.example für versionierte Vorlagen ohne echte Keys.\n", file=sys.stderr)
        return 1

    # 2. Gate: API-Keys & Secrets im Diff prüfen
    findings = check_staged_secrets()
    if findings:
        print("\n" + "=" * 76, file=sys.stderr)
        print("❌ COMMIT ABGEBROCHEN: Mögliche API-Keys oder Secrets im Diff entdeckt!", file=sys.stderr)
        print("=" * 76, file=sys.stderr)
        for finding in findings:
            print(f"  🛑 {finding.file_path}:{finding.line_number} [{finding.rule}]", file=sys.stderr)
            print(f"     Ausschnitt: {finding.snippet}", file=sys.stderr)
        print("\nSicherheitsregel:", file=sys.stderr)
        print("  Echte Credentials, private Schlüssel oder Provider-Tokens gehören", file=sys.stderr)
        print("  ausschließlich in die lokale .env-Datei, niemals in den Code.", file=sys.stderr)
        print("  Ersetze den Wert durch os.getenv(...) oder einen Dummy-Platzhalter.\n", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
