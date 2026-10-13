#!/bin/sh
# scripts/install-git-hooks.sh – installiert das Pre-Commit Gate (Secret- & .env-Schutz + Linting)
# für macOS/Linux-Mitwirkende (Windows: scripts/install-git-hooks.ps1).
#
# Einmalig ausführen (aus dem Projekt-Root):
#   sh scripts/install-git-hooks.sh

set -e

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "Kein Git-Repository gefunden. Bitte aus dem Projekt-Root heraus ausführen." >&2
    exit 1
}

# 1. Git hooksPath konfigurieren
git config core.hooksPath scripts/git-hooks

# 2. Fallback: Datei nach .git/hooks/pre-commit kopieren
hooks_dir="$repo_root/.git/hooks"
mkdir -p "$hooks_dir"

cp "$repo_root/scripts/git-hooks/pre-commit" "$hooks_dir/pre-commit"
chmod +x "$hooks_dir/pre-commit"
chmod +x "$repo_root/scripts/git-hooks/pre-commit"

echo "✅ Pre-Commit-Sicherheits-Gate erfolgreich aktiviert: $hooks_dir/pre-commit"
echo "   Prüfungen vor jedem 'git commit':"
echo "     1. 🛑 Blockiert .env-Dateien (.env, .env.local, etc. außer .env.example)"
echo "     2. 🛑 Blockiert API-Keys & Secrets im Diff (Google, AWS, Anthropic, OpenAI, etc.)"
echo "     3. 🧹 Führt 'ruff check' auf gestagten Python-Dateien aus"
