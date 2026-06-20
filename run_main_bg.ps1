$env:PYTHONUNBUFFERED = "1"
$p = Start-Process -NoNewWindow -FilePath "python" -ArgumentList "main.py" -RedirectStandardOutput "main_stdout.txt" -RedirectStandardError "main_stderr.txt" -PassThru
$p.Id | Set-Content -Path "main_pid.txt"
Write-Output "PID: $($p.Id)"
