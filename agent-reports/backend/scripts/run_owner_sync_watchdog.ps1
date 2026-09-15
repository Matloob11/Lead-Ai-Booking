# Owner Data sync with auto-restart (Python watchdog).
# Stop: create agent-reports/backend/owner-sync.stop
$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $PSScriptRoot
Set-Location $Backend
$env:PYTHONPATH = $Backend
$env:PYTHONUNBUFFERED = "1"
$stop = Join-Path $Backend "owner-sync.stop"
if (Test-Path $stop) { Remove-Item $stop -Force }
$Python = (Get-Command python -ErrorAction Stop).Source
$outLog = Join-Path $Backend "owner-sync-watchdog.launcher.out.log"
$errLog = Join-Path $Backend "owner-sync-watchdog.launcher.err.log"
Start-Process -WorkingDirectory $Backend -FilePath $Python `
    -ArgumentList @("scripts/owner_sync_watchdog.py") `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden
Write-Host "started owner_sync_watchdog.py (stop file: owner-sync.stop)"
