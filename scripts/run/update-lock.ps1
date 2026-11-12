# The update lock (T-0029), dot-sourced by install-always-on.ps1, update-hub.ps1 and
# run-hub.ps1. While a script replaces the runtime copy, the watchdog trigger (every 5 min)
# could start the supervisor on half-built files; the supervisor waits while the lock is held.
# The lock holds the updating script's process id. It is stale once that process is gone
# (the update crashed or was closed), or after 60 minutes whatever the process id says
# (Windows reuses ids).

function Get-UpdateLock([string]$DataDir) { return (Join-Path $DataDir "updating.lock") }

function Lock-Update([string]$DataDir) {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    Set-Content -Path (Get-UpdateLock $DataDir) -Value $PID -Encoding ascii
}

function Unlock-Update([string]$DataDir) {
    # Only this process's own lock: a failing preflight must not free another update's lock.
    $lock = Get-UpdateLock $DataDir
    if ((Test-Path $lock) -and ((Get-Content $lock -Raw).Trim() -eq "$PID")) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
    }
}

function Test-UpdateLocked([string]$DataDir, [int]$MaxMinutes = 60) {
    $lock = Get-UpdateLock $DataDir
    if (-not (Test-Path $lock)) { return $false }
    $item = Get-Item $lock -ErrorAction SilentlyContinue
    if (-not $item -or $item.LastWriteTime -lt (Get-Date).AddMinutes(-$MaxMinutes)) { return $false }
    $holder = 0
    [void][int]::TryParse(((Get-Content $lock -Raw) -as [string]).Trim(), [ref]$holder)
    return [bool]($holder -and (Get-Process -Id $holder -ErrorAction SilentlyContinue))
}

function Wait-For-Update([string]$DataDir, [int]$MaxMinutes = 60, [int]$PollSeconds = 5) {
    while (Test-UpdateLocked $DataDir $MaxMinutes) { Start-Sleep -Seconds $PollSeconds }
}
