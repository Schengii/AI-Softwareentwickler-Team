# scripts/run_production_monitor.ps1 – Wrapper für den Windows-Taskplaner-Eintrag "AI-Team-ProductionMonitor"
#
# Führt EINEN Poll-Zyklus über alle per `/deploy-cloud --real` deployten Projekte aus
# (core/production_monitor.py, siehe `python main.py --check-deployments` in main.py) und
# hängt die Ausgabe an logs/production_monitor.log an (logs/ ist in .gitignore).
#
# WICHTIG (anders als run_issue_watcher.ps1): der Deployment-Zustand pro Projekt
# (.ai_team_deployment.json, core/deployment_status.py) liegt gitignored direkt im jeweiligen
# workspace/<projekt>-Verzeichnis - existiert NUR auf diesem lokalen Rechner. Ein GitHub-
# Actions-Runner mit frischem Checkout kennt daher NIE ein echtes Deployment und würde bei
# jedem Lauf scheinbar erfolgreich, aber wirkungslos durchlaufen (deshalb bewusst NICHT in
# .github/workflows/ai-team-scheduler.yml verdrahtet). Der Windows-Taskplaner auf DIESEM
# Rechner ist deshalb der einzige sinnvolle Ort für diesen Zyklus.

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -Path $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$LogFile = Join-Path $LogDir "production_monitor.log"

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "--- [$Timestamp] Poll-Zyklus gestartet ---"

& python main.py --check-deployments 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8

Add-Content -Path $LogFile -Value "--- [$Timestamp] Poll-Zyklus beendet (Exit-Code: $LASTEXITCODE) ---"
