$env:PYTHONUNBUFFERED = "1"
$logFile = Join-Path $PSScriptRoot "agent_logs" "ecosystem_daemon.log"
$pidFile = Join-Path $PSScriptRoot "ecosystem_daemon.pid"

# Kill existing if running
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile
    try { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 1
}

# Start ecosystem in production mode with background Python
$p = Start-Process -NoNewWindow -FilePath "python" -ArgumentList "awaken.py --mode boot --production" `
    -WorkingDirectory $PSScriptRoot `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $logFile `
    -PassThru

$p.Id | Set-Content -Path $pidFile
Write-Output "Ecosystem daemon started (PID: $($p.Id))"
Write-Output "Logs: $logFile"
Write-Output "Stop: Stop-Process -Id $($p.Id) -Force"
