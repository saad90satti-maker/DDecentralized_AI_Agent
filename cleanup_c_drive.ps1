# =============================================================================
# SAFE CLEANUP SCRIPT — C Drive Recovery (Dry-Run Mode by Default)
# =============================================================================
# WARNING: Review every line before execution. This script is GENERATED
# for review purposes. Do NOT run without explicit confirmation.
# =============================================================================

# --- CONFIGURATION ---
$DRY_RUN = $true  # Set to $false to actually delete
$WORKSPACE = "D:\DDecentralized_AI_Agent"

Write-Host "=== C DRIVE CLEANUP REPORT ===" -ForegroundColor Yellow
Write-Host "C: Free Space: 0.0 GB (CRITICAL)" -ForegroundColor Red
Write-Host "Dry Run: $DRY_RUN`n" -ForegroundColor Cyan

# =============================================================================
# 1. Temp Files (Safe to Delete)
# =============================================================================
Write-Host "--- 1. Temp Files ---" -ForegroundColor Cyan

$tempTargets = @(
    @{Path = "$env:TEMP\nstA0C6.tmp"; SizeMB = 680.5; Desc = "Unknown large temp blob"},
    @{Path = "$env:TEMP\IBfeMhNM"; SizeMB = 135.1; Desc = "Unknown temp directory"},
    @{Path = "$env:TEMP\0F80E99A-F6C1-420C-8716-BCF5761D273D"; SizeMB = 9.8; Desc = "Temp GUID folder"},
    @{Path = "$env:TEMP\1481776F-0059-4D41-A00A-182AB7A4E474"; SizeMB = 9.8; Desc = "Temp GUID folder"},
    @{Path = "$env:TEMP\iu-14D2N.tmp"; SizeMB = 3.4; Desc = "Temp file"},
    @{Path = "$env:TEMP\node-compile-cache"; SizeMB = 1.3; Desc = "Node.js compile cache"}
)

$tempTotal = 0
foreach ($t in $tempTargets) {
    if (Test-Path $t.Path) {
        Write-Host "  [$($t.SizeMB) MB] $($t.Desc)`n    $($t.Path)"
        $tempTotal += $t.SizeMB
        if (-not $DRY_RUN) {
            if (Test-Path -LiteralPath $t.Path -PathType Container) {
                Remove-Item -LiteralPath $t.Path -Recurse -Force -ErrorAction SilentlyContinue
            } else {
                Remove-Item -LiteralPath $t.Path -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
Write-Host "  Temp recoverable: ~$tempTotal MB`n" -ForegroundColor Green

# =============================================================================
# 2. Ollama Models (11 GB — Major Space Hog)
# =============================================================================
Write-Host "--- 2. Ollama Models (~11,015 MB) ---" -ForegroundColor Cyan
Write-Host "  Path: $env:USERPROFILE\.ollama" -ForegroundColor Yellow
Write-Host "  ACTION REQUIRED: Review models before deleting."
Write-Host "  Options:" -ForegroundColor Yellow
Write-Host "    a) Keep Ollama entirely (no space saved)"
Write-Host "    b) Remove specific models: ollama list -> ollama rm <model>"
Write-Host "    c) Move to D: Drive (requires symlink)"
Write-Host "  Example migration:" -ForegroundColor Gray
Write-Host "    Move-Item `"$env:USERPROFILE\.ollama`" `"D:\.ollama`"" -ForegroundColor Gray
Write-Host "    New-Item -ItemType SymbolicLink -Path `"$env:USERPROFILE\.ollama`" -Target `"D:\.ollama`"`n"

# =============================================================================
# 3. Windows Browser Caches
# =============================================================================
Write-Host "--- 3. Browser Caches ---" -ForegroundColor Cyan

$browserCaches = @(
    @{Path = "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache"; Desc = "Chrome cache"},
    @{Path = "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Code Cache"; Desc = "Chrome code cache"},
    @{Path = "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Service Worker\CacheStorage"; Desc = "Chrome service worker"},
    @{Path = "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache"; Desc = "Edge cache"}
)

foreach ($b in $browserCaches) {
    if (Test-Path $b.Path) {
        Write-Host "  Found: $($b.Desc)"
        Write-Host "    $($b.Path)"
        if (-not $DRY_RUN) {
            Remove-Item -LiteralPath "$($b.Path)\*" -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "`n"

# =============================================================================
# 4. Python Cache Files
# =============================================================================
Write-Host "--- 4. Python Cache Files ---" -ForegroundColor Cyan

Get-ChildItem -Path $WORKSPACE -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
    $size = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($size -gt 0) {
        $sizeMB = [math]::Round($size/1MB, 2)
        Write-Host "  Found __pycache__: $($_.FullName) ($sizeMB MB)"
        if ((-not $DRY_RUN) -and ($sizeMB -gt 1)) {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "`n"

# =============================================================================
# 5. Hermes Agent Cache  (specifically pip cache, node_modules)
# =============================================================================
Write-Host "--- 5. Hermes Agent Caches ---" -ForegroundColor Cyan

$hermesCachePaths = @(
    "$env:LOCALAPPDATA\hermes\hermes-agent\node_modules",
    "$env:LOCALAPPDATA\hermes\hermes-agent\.venv"
)
foreach ($p in $hermesCachePaths) {
    if (Test-Path $p) {
        $size = (Get-ChildItem $p -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        $sizeMB = [math]::Round($size/1MB, 1)
        Write-Host "  $p ($sizeMB MB)"
    }
}
Write-Host "`n"

# =============================================================================
# 6. Windows Temp / Prefetch
# =============================================================================
Write-Host "--- 6. Windows System Temp ---" -ForegroundColor Cyan
$winTemp = @(
    @{Path = "C:\Windows\Temp"; Desc = "Windows Temp"},
    @{Path = "C:\Windows\Prefetch"; Desc = "Windows Prefetch"}
)
foreach ($w in $winTemp) {
    Write-Host "  Review manually: $($w.Desc) at $($w.Path)" -ForegroundColor Gray
}
Write-Host "`n"

# =============================================================================
# Summary
# =============================================================================
Write-Host "=== SUMMARY ===" -ForegroundColor Yellow
Write-Host "Immediately reclaimable from Temp: ~840 MB" -ForegroundColor Green
Write-Host "Potentially reclaimable from Ollama: ~11,015 MB" -ForegroundColor Green
Write-Host "Browser caches: variable (run browsers once to estimate)" -ForegroundColor Green
Write-Host "`nBEST APPROACH:" -ForegroundColor Yellow
Write-Host "1. Move workspace to D: (saves ~20 MB workspace itself)" -ForegroundColor White
Write-Host "2. Move .ollama to D: (saves 11,015 MB)" -ForegroundColor White
Write-Host "3. Clear temp files (saves ~840 MB)" -ForegroundColor White
Write-Host "4. Clear browser caches (saves variable)" -ForegroundColor White
Write-Host "5. Prune old Ollama models (ollama list -> ollama rm)" -ForegroundColor White
Write-Host "`nRun with `$DRY_RUN = `$false to execute deletions" -ForegroundColor Red
