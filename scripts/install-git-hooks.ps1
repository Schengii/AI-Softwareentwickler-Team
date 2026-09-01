# scripts/install-git-hooks.ps1 – installiert das lokale Lint-Gate (scripts/git-hooks/pre-commit)
#
# Einmalig ausführen (aus dem Projekt-Root):
#   powershell -ExecutionPolicy Bypass -File scripts/install-git-hooks.ps1
#
# .git/hooks/ wird von Git selbst nicht versioniert - deshalb liegt der eigentliche Hook
# versioniert unter scripts/git-hooks/pre-commit und wird hier nur an die Stelle kopiert,
# an der Git ihn tatsächlich ausführt.

$ErrorActionPreference = "Stop"

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    Write-Error "Kein Git-Repository gefunden. Bitte aus dem Projekt-Root heraus ausführen."
    exit 1
}

$hooksDir = Join-Path $repoRoot ".git/hooks"
if (-not (Test-Path $hooksDir)) {
    New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
}

$source = Join-Path $repoRoot "scripts/git-hooks/pre-commit"
$target = Join-Path $hooksDir "pre-commit"

Copy-Item -Path $source -Destination $target -Force

Write-Host "✅ Pre-Commit-Lint-Gate installiert: $target"
Write-Host "   Läuft ab jetzt automatisch vor jedem 'git commit' (ruff check .)."
Write-Host "   Bewusst umgehen: git commit --no-verify"
