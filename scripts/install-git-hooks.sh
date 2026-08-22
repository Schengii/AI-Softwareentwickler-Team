#!/bin/sh
# scripts/install-git-hooks.sh – installiert das lokale Lint-Gate (scripts/git-hooks/pre-commit)
# für macOS/Linux-Mitwirkende (Windows: scripts/install-git-hooks.ps1).
#
# Einmalig ausführen (aus dem Projekt-Root):
#   sh scripts/install-git-hooks.sh

set -e

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "Kein Git-Repository gefunden. Bitte aus dem Projekt-Root heraus ausführen." >&2
    exit 1
}

hooks_dir="$repo_root/.git/hooks"
mkdir -p "$hooks_dir"

cp "$repo_root/scripts/git-hooks/pre-commit" "$hooks_dir/pre-commit"
chmod +x "$hooks_dir/pre-commit"

echo "✅ Pre-Commit-Lint-Gate installiert: $hooks_dir/pre-commit"
echo "   Läuft ab jetzt automatisch vor jedem 'git commit' (ruff check .)."
echo "   Bewusst umgehen: git commit --no-verify"
