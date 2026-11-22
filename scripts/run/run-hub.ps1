# Keeps the Personal OS Hub running: starts it, and starts it again if it ever exits.
# Started at logon by the "PersonalOS Hub" scheduled task (install-always-on.ps1).
#
# The desktop agent (T-0063, ADR 0043) is kept running the same way, but only while
# $DataDir\agent.enabled exists. scripts\run\enable-agent.ps1 pairs the agent and writes
# that file; -Disable removes it. Nothing about the agent changes until the user runs it.
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
$agentFlag = Join-Path $DataDir "agent.enabled"
$agentPidFile = Join-Path $DataDir "agent.pid"
$keepRuns = 10                     # per-run output files kept (newest first)
# Agent exit codes a restart cannot fix (apps/desktop_agent/__main__.py): 2 not paired,
# 3 token rejected, 4 replaced by another agent. The supervisor then waits until
# agent.enabled is written again, which enable-agent.ps1 does after pairing.
$agentHoldCodes = @(2, 3, 4)

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

function Start-Run([string]$uvExe, [string]$module, [string]$prefix, [string[]]$extra) {
    # Each run writes its own files, so a crash's output survives the next start.
    Get-ChildItem $logs -Filter "$prefix-run-*.log" | Sort-Object Name -Descending |
        Select-Object -Skip ($keepRuns * 2) | Remove-Item -Force -ErrorAction SilentlyContinue
    $run = Get-Date -Format "yyyyMMdd-HHmmss"
    $out = Join-Path $logs "$prefix-run-$run-out.log"
    $err = Join-Path $logs "$prefix-run-$run-err.log"
    $arguments = @("run", "--frozen", "python", "-m", $module) + $extra
    $proc = Start-Process -FilePath $uvExe -ArgumentList $arguments -WorkingDirectory $CopyDir `
        -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $proc.Handle  # Windows PowerShell 5.1 only reports ExitCode if the handle was read
    Write-Log "started $module from $CopyDir (pid $($proc.Id), output: $prefix-run-$run-*.log)"
    return $proc
}

function Get-FlagStamp {
    $item = Get-Item $agentFlag -ErrorAction SilentlyContinue
    if ($item) { return $item.LastWriteTimeUtc.Ticks }
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

$hub = $null
$hubNext = Get-Date            # when the Hub may be started (again)
$agent = $null
$agentNext = Get-Date
$agentHold = $null             # agent.enabled's stamp when the agent last needed the user
$agentStartStamp = $null       # agent.enabled's stamp when the running agent was started

while ($true) {
    Wait-For-Update $DataDir

    # --- the Hub ---
    if ($hub -and $hub.HasExited) {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Log "Hub exited with code $($hub.ExitCode); starting again in 10 s"
        $hub = $null
        $hubNext = (Get-Date).AddSeconds(10)
    }
    if (-not $hub -and (Get-Date) -ge $hubNext) {
        $uvExe = Find-Uv
        if (-not $uvExe) {
            Write-Log "uv was not found; trying again in 60 s"
            $hubNext = (Get-Date).AddSeconds(60)
        } else {
            Write-Log "starting Hub with data_dir=$DataDir"
            $hub = Start-Run $uvExe "apps.hub" "hub" @()
            Set-Content -Path $pidFile -Value $hub.Id -Encoding ascii
        }
    }

    # --- the desktop agent, only while agent.enabled exists ---
    $stamp = Get-FlagStamp
    if ($agent -and $agent.HasExited) {
        $code = $agent.ExitCode
        Remove-Item $agentPidFile -Force -ErrorAction SilentlyContinue
        $agent = $null
        if ($agentHoldCodes -contains $code) {
            # The stamp at its start, not now: a re-pair that rewrote the flag while this
            # agent was exiting must release the hold, not be held itself.
            $agentHold = $agentStartStamp
            Write-Log "agent exited with code ${code}: it needs pairing (scripts\run\enable-agent.ps1); not restarting until then"
        } else {
            Write-Log "agent exited with code ${code}; starting again in 10 s"
        }
        $agentNext = (Get-Date).AddSeconds(10)
    }
    if ($agent -and $null -eq $stamp) {
        & taskkill.exe /PID $agent.Id /T /F 2>$null | Out-Null
        Remove-Item $agentPidFile -Force -ErrorAction SilentlyContinue
        Write-Log "agent.enabled was removed: agent stopped"
        $agent = $null
        $agentHold = $null
    }
    $held = ($null -ne $agentHold) -and ($agentHold -eq $stamp)
    if (-not $agent -and $null -ne $stamp -and -not $held -and $hub -and (Get-Date) -ge $agentNext) {
        $agentHold = $null
        $uvExe = Find-Uv
        if ($uvExe) {
            $agentStartStamp = $stamp
            $agent = Start-Run $uvExe "apps.desktop_agent" "agent" @("run")
            Set-Content -Path $agentPidFile -Value $agent.Id -Encoding ascii
        }
    }

    Start-Sleep -Seconds 2
}
