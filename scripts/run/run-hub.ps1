# Keeps the Personal OS Hub running: starts it, and starts it again if it ever exits.
# Started at logon by the "PersonalOS Hub" scheduled task (install-always-on.ps1).
param(
    [Parameter(Mandatory = $true)][string]$CopyDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$Uv = ""
)

$ErrorActionPreference = "Continue"
$logs = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs "hub.log"   # the supervisor's own notes
$pidFile = Join-Path $DataDir "hub.pid"
$keepRuns = 10                     # per-run output files kept (newest first)

function Write-Log([string]$text) {
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) {
        Move-Item -Force $log "$log.1"
    }
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $log -Value "$stamp supervisor: $text" -Encoding utf8
}

function Find-Uv {
    if ($Uv -and (Test-Path $Uv)) { return $Uv }
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    return $null
}

$lockScript = Join-Path $PSScriptRoot "update-lock.ps1"
if (Test-Path $lockScript) {
    . $lockScript  # Wait-For-Update: waits while an update replaces the copy
} else {
    # A partial checkout mid-update: do not exit (the watchdog would wait 5 min); start as before.
    function Wait-For-Update([string]$DataDir) {}
}

Wait-For-Update $DataDir
Write-Log "supervisor started (pid $PID)"
$env:POS_DATA_DIR = $DataDir
$env:PYTHONIOENCODING = "utf-8"
Set-Location $CopyDir

while ($true) {
    # Each run writes its own files, so a crash's output survives the next start.
    Get-ChildItem $logs -Filter "hub-run-*.log" | Sort-Object Name -Descending |
        Select-Object -Skip ($keepRuns * 2) | Remove-Item -Force -ErrorAction SilentlyContinue
    Wait-For-Update $DataDir
    $uvExe = Find-Uv
    if (-not $uvExe) {
        Write-Log "uv was not found; trying again in 60 s"
        Start-Sleep -Seconds 60
        continue
    }
    $run = Get-Date -Format "yyyyMMdd-HHmmss"
    $out = Join-Path $logs "hub-run-$run-out.log"
    $err = Join-Path $logs "hub-run-$run-err.log"
    Write-Log "starting Hub from $CopyDir with data_dir=$DataDir (output: hub-run-$run-*.log)"
    $proc = Start-Process -FilePath $uvExe -ArgumentList @("run", "--frozen", "python", "-m", "apps.hub") `
        -WorkingDirectory $CopyDir -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $proc.Handle  # Windows PowerShell 5.1 only reports ExitCode if the handle was read
    Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
    $proc.WaitForExit()
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Log "Hub exited with code $($proc.ExitCode); starting again in 10 s"
    Start-Sleep -Seconds 10
}
