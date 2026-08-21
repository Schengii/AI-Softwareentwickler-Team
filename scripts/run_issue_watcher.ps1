# scripts/run_issue_watcher.ps1 – Wrapper für den Windows-Taskplaner-Eintrag "AI-Team-IssueWatcher"
#
# Führt EINEN Poll-Zyklus über offene GitHub-Issues aus (core/issue_watcher.py, siehe
# `python main.py --check-issues` in main.py) und hängt die Ausgabe an logs/issue_watcher.log
# an (logs/ ist in .gitignore, wird nicht versioniert). Der Taskplaner ruft dieses Skript
# wiederkehrend auf (Standard: alle 15 Minuten) - kein Dauerprozess, ein Aufruf = ein Zyklus,
# siehe core/issue_watcher.py für die Begründung ("Cron/Taskplaner statt eigenem Scheduler").

$ErrorActionPreference = "Continue"
# PowerShell muss die UTF-8-Bytes, die main.py's Windows-Konsolen-Fix ausgibt, auch als UTF-8
# DEKODIEREN (nicht nur das Log als UTF-8 schreiben) - sonst entstehen Mojibake-Zeichen bei
# Emojis/Umlauten im Log, obwohl die Zieldatei selbst korrekt UTF-8-kodiert ist.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -Path $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$LogFile = Join-Path $LogDir "issue_watcher.log"

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "--- [$Timestamp] Poll-Zyklus gestartet ---"

# 2>&1 + Out-File -Encoding utf8 statt *>> - der PowerShell-5.1-Redirect-Operator schreibt
# standardmäßig UTF-16LE, was main.py's UTF-8-Konsolenausgabe (Windows-Fix in main.py) im Log
# unlesbar gemacht hätte. 2>&1 fängt auch Fehlerausgaben (z.B. fehlende .env/API-Keys) mit ein.
& python main.py --check-issues 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8

Add-Content -Path $LogFile -Value "--- [$Timestamp] Poll-Zyklus beendet (Exit-Code: $LASTEXITCODE) ---"
