# scripts/run_backlog_worker.ps1 – Wrapper für den Windows-Taskplaner-Eintrag "AI-Team-BacklogWorker"
#
# Führt EINEN Poll-Zyklus über bereits im Backlog wartende "todo"-Tickets aus
# (core/backlog_worker.py, siehe `python main.py --work-backlog` in main.py) und hängt die
# Ausgabe an logs/backlog_worker.log an (logs/ ist in .gitignore, wird nicht versioniert).
#
# WICHTIG (anders als run_issue_watcher.ps1): memory/backlog.json ist gitignored - dessen
# "todo"-Tickets existieren NUR auf diesem lokalen Rechner. Ein GitHub-Actions-Runner mit
# frischem Checkout hätte hier IMMER ein leeres Backlog und würde bei jedem Lauf scheinbar
# erfolgreich, aber wirkungslos durchlaufen (deshalb bewusst NICHT in
# .github/workflows/ai-team-scheduler.yml verdrahtet - siehe dort für die Begründung bei den
# stateless-sicheren Zyklen). Der Windows-Taskplaner auf DIESEM Rechner ist deshalb der
# einzige sinnvolle Ort für diesen Zyklus.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -Path $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$LogFile = Join-Path $LogDir "backlog_worker.log"

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "--- [$Timestamp] Poll-Zyklus gestartet ---"

& python main.py --work-backlog 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8

Add-Content -Path $LogFile -Value "--- [$Timestamp] Poll-Zyklus beendet (Exit-Code: $LASTEXITCODE) ---"
