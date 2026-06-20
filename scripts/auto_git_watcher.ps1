param(
    [string]$RepoPath = "D:\DDecentralized_AI_Agent",
    [int]$DebounceSeconds = 30,
    [string]$LogFile = "D:\DDecentralized_AI_Agent\agent_logs\git_watcher.log"
)

$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Out-File -FilePath $LogFile -Append
    Write-Host "$timestamp - $Message"
}

Write-Log "Auto Git Watcher started. Monitoring: $RepoPath"

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $RepoPath
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]::FileName -bor [System.IO.NotifyFilters]::LastWrite -bor [System.IO.NotifyFilters]::DirectoryName
$watcher.EnableRaisingEvents = $true

$excludeDirs = @('__pycache__', '.git', '.pytest_cache', 'venv', '.venv', 'node_modules',
                 'agent_logs', 'agent_data', 'session_data', 'scratch', '__pycache__',
                 '__pycache__', '.opencode')
$excludeExts = @('.pyc', '.log', '.tmp', '.bak', '.swp')

$timer = New-Object System.Timers.Timer
$timer.Interval = $DebounceSeconds * 1000
$timer.AutoReset = $false
$changed = $false

$action = {
    $changed = $true
    $timer.Stop()
    $timer.Start()
}

$onChange = Register-ObjectEvent -InputObject $watcher -EventName "Changed" -Action $action
$onCreate = Register-ObjectEvent -InputObject $watcher -EventName "Created" -Action $action
$onDelete = Register-ObjectEvent -InputObject $watcher -EventName "Deleted" -Action $action
$onRename = Register-ObjectEvent -InputObject $watcher -EventName "Renamed" -Action $action

$timer.Add_Elapsed({
    try {
        Push-Location $RepoPath
        $status = git status --porcelain
        if ($status) {
            $ignored = $false
            foreach ($line in $status) {
                $file = $line.Substring(3)
                $dir = Split-Path $file -Parent
                $shouldSkip = $false
                foreach ($ex in $excludeDirs) { if ($file -like "$ex/*" -or $file -eq $ex) { $shouldSkip = $true; break } }
                foreach ($ex in $excludeExts) { if ($file -like "*$ex") { $shouldSkip = $true; break } }
                if (-not $shouldSkip) { $ignored = $true }
            }
            if ($ignored) {
                git add -A 2>&1 | Out-Null
                $commitMsg = "Auto commit: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
                git commit -m "$commitMsg" 2>&1 | Out-Null
                $pushResult = git push 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "Pushed: $commitMsg"
                } else {
                    Write-Log "Push failed: $pushResult"
                }
            }
        }
        Pop-Location
    } catch {
        Write-Log "Error: $_"
        try { Pop-Location } catch {}
    }
})

Write-Log "Watcher active. Debounce: ${DebounceSeconds}s. Press Ctrl+C to stop."

while ($true) {
    Start-Sleep -Seconds 10
}
