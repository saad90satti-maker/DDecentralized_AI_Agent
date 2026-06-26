# Setup Ecosystem as a Windows Scheduled Task (persistent across reboots)
# Run this as Administrator:  powershell -ExecutionPolicy Bypass .\setup_ecosystem_service.ps1

$taskName = "DecentralizedAI-Ecosystem"
$scriptPath = Join-Path $PSScriptRoot "run_ecosystem_bg.ps1"

Write-Output "Setting up scheduled task: $taskName"
Write-Output "Script: $scriptPath"

# Remove existing task if present
schtasks /Delete /TN $taskName /F 2>$null

# Create new task: run at system startup, as current user
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register the task
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Output ""
Write-Output "Scheduled task created: $taskName"
Write-Output "  Trigger: At system startup"
Write-Output "  Action: powershell.exe -File `"$scriptPath`""
Write-Output ""
Write-Output "Manual commands:"
Write-Output "  Start:   Start-ScheduledTask -TaskName `"$taskName`""
Write-Output "  Stop:    Stop-ScheduledTask -TaskName `"$taskName`""
Write-Output "  Status:  Get-ScheduledTask -TaskName `"$taskName`" | Select-Object State"
Write-Output "  Remove:  Unregister-ScheduledTask -TaskName `"$taskName`" -Confirm:`$false"
