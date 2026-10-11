# scripts/install-git-hooks.ps1 – installiert das Pre-Commit Gate (Secret- & .env-Schutz + Linting)
#
# Einmalig ausführen (aus dem Projekt-Root):
#   powershell -ExecutionPolicy Bypass -File scripts/install-git-hooks.ps1
#
# Aktiviert den Pre-Commit-Hook sowohl über Git core.hooksPath als auch als Fallback in .git/hooks/pre-commit.

$ErrorActionPreference = "Stop"

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    Write-Error "Kein Git-Repository gefunden. Bitte aus dem Projekt-Root heraus ausführen."
    exit 1
}

# 1. Git hooksPath auf scripts/git-hooks konfigurieren
& git config core.hooksPath scripts/git-hooks

# 2. Fallback: Datei nach .git/hooks/pre-commit kopieren
$hooksDir = Join-Path $repoRoot ".git/hooks"
if (-not (Test-Path $hooksDir)) {
    New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
}

$source = Join-Path $repoRoot "scripts/git-hooks/pre-commit"
$target = Join-Path $hooksDir "pre-commit"

Copy-Item -Path $source -Destination $target -Force

Write-Host "✅ Pre-Commit-Sicherheits-Gate erfolgreich aktiviert!" -ForegroundColor Green
Write-Host "   Pfade: core.hooksPath=scripts/git-hooks & $target"
Write-Host "   Prüfungen vor jedem 'git commit':"
Write-Host "     1. 🛑 Blockiert .env-Dateien (.env, .env.local, etc. außer .env.example)"
Write-Host "     2. 🛑 Blockiert API-Keys & Secrets im Diff (Google, AWS, Anthropic, OpenAI, etc.)"
Write-Host "     3. 🧹 Führt 'ruff check' auf gestagten Python-Dateien aus"
