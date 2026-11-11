# Makes the Personal OS Hub always available on this PC (ADR 0021).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run\install-always-on.ps1 [-Ref <commit or branch>]
#
# - Puts a separate copy of the code at -CopyDir (a git worktree, detached at -Ref), so
#   development never disturbs the running Hub. Running this again updates that copy.
# - Keeps the Hub's data at -DataDir.
# - Registers a per-user scheduled task "PersonalOS Hub" (no administrator rights) that
#   starts the Hub hidden at logon and keeps it running, then starts it now.
# Undo: scripts\run\uninstall-always-on.ps1
param(
    [string]$CopyDir = "D:\dev\personal-os-run",
    [string]$DataDir = "D:\dev\personal-os-data",
    [string]$Ref = "HEAD",
    # Prepare the copy and the data folder only: no scheduled task, nothing started.
    [switch]$PrepareOnly
)

# Native tools (git, uv, pnpm) write progress to stderr; failures are caught by exit code.
$ErrorActionPreference = "Continue"
$CopyDir = $CopyDir.TrimEnd('\')
$DataDir = $DataDir.TrimEnd('\')
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$taskName = "PersonalOS Hub"
$user = "$env:USERDOMAIN\$env:USERNAME"

function Step([string]$text) { Write-Output "== $text" }
function Fail([string]$text) { Write-Output "FAILED: $text"; exit 1 }

function Get-Listener {
    # The process listening on 8765 and its parent, or $null.
    $conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($conn.OwningProcess)"
    if (-not $proc) { return $null }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)"
    return [pscustomobject]@{ Proc = $proc; Parent = $parent }
}

function Describe-Listener($l) {
    $text = "pid $($l.Proc.ProcessId) $($l.Proc.ExecutablePath)"
    if ($l.Parent) { $text += " <- $($l.Parent.ExecutablePath)" }
    return $text
}

function Hub-From-Copy {
    # True only if the process listening on 8765 is this copy's Hub.
    $l = Get-Listener
    if (-not $l -or $l.Proc.CommandLine -notlike "*apps.hub*") { return $false }
    if ($l.Proc.ExecutablePath -like "$CopyDir\*") { return $true }
    # On Windows a venv's python.exe is a launcher: the interpreter that owns the socket is
    # its child and runs from the base Python install, so check the parent too.
    return $l.Parent -and $l.Parent.ExecutablePath -like "$CopyDir\*"
}

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
$pnpm = (Get-Command pnpm -ErrorAction SilentlyContinue).Source
if (-not $uv -or -not $pnpm) { Fail "uv and pnpm must be on PATH" }
$commit = (git -C $repo rev-parse $Ref 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $commit) { Fail "unknown -Ref '$Ref'" }
$commit = $commit.Trim()
if ($DataDir -like "$CopyDir\*") { Fail "-DataDir must not be inside -CopyDir" }

$running = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" |
    Where-Object { $_.CommandLine -like "*run-hub.ps1*" -and $_.CommandLine -like "*$CopyDir*" }
$hadTask = [bool](Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)
if ($PrepareOnly -and $running) {
    Fail "a Hub is running from $CopyDir; stop it first (scripts\run\stop-hub.ps1)"
}
if (-not $PrepareOnly) {
    Step "stop the running Hub, if any"
    if ($hadTask) { Stop-ScheduledTask -TaskName $taskName }
    & (Join-Path $PSScriptRoot "stop-hub.ps1") -CopyDir $CopyDir -DataDir $DataDir
}

$blocker = Get-Listener
if (-not $PrepareOnly -and $blocker) {
    # Something we could not prove ours still holds the port; the new Hub could never start.
    if ($hadTask) { Start-ScheduledTask -TaskName $taskName }
    Fail "port 8765 is in use by $(Describe-Listener $blocker); stop it first"
}

function Restore-And-Fail([string]$text) {
    # A failed update must not leave the site down: start the previous setup again.
    if ($hadTask -and -not $PrepareOnly) { Start-ScheduledTask -TaskName $taskName }
    Fail $text
}

Step "runtime copy at $CopyDir (commit $($commit.Substring(0, 10)))"
if (Test-Path (Join-Path $CopyDir ".git")) {
    git -C $CopyDir checkout --quiet --detach $commit
} else {
    git -C $repo worktree add --detach $CopyDir $commit
}
if ($LASTEXITCODE -ne 0) { Restore-And-Fail "git could not prepare $CopyDir" }
$runner = Join-Path $CopyDir "scripts\run\run-hub.ps1"
if (-not (Test-Path $runner)) {
    Restore-And-Fail "commit $Ref has no scripts\run\run-hub.ps1; use a newer -Ref"
}

Push-Location $CopyDir
Step "install Python packages in the copy (from the local cache)"
& $uv sync --frozen
$ok = $LASTEXITCODE -eq 0
if ($ok) {
    Step "build the web page in the copy"
    & $pnpm install --frozen-lockfile --prefer-offline
    $ok = $LASTEXITCODE -eq 0
}
if ($ok) {
    & $pnpm --dir apps/web build
    $ok = $LASTEXITCODE -eq 0
}
Pop-Location
if (-not $ok) { Restore-And-Fail "installing or building in $CopyDir failed (see above)" }

Step "data folder $DataDir"
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null
if ($PrepareOnly) {
    Write-Output "prepared $CopyDir and $DataDir; no scheduled task was registered"
    exit 0
}

Step "register the scheduled task '$taskName' (starts at your logon, hidden)"
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`" " +
    "-CopyDir `"$CopyDir`" -DataDir `"$DataDir`" -Uv `"$uv`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $CopyDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
# The supervisor restarts the Hub itself; Task Scheduler only restarts the supervisor if
# powershell.exe exits with an error (3 times, then until the next logon).
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Priority 5
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Personal OS Hub on http://127.0.0.1:8765 (ADR 0021)" -Force | Out-Null
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    Fail "the scheduled task could not be registered"
}

Step "start it now"
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
        if ($health.status -eq "ok" -and (Hub-From-Copy)) {
            Write-Output "Hub is up: http://127.0.0.1:8765 (schema $($health.schema_version))"
            exit 0
        }
    } catch {
        # not up yet
    }
    Start-Sleep -Seconds 2
}
$l = Get-Listener
if ($l) {
    Fail "a Hub answers on 8765 but not from ${CopyDir}: $(Describe-Listener $l); see $DataDir\logs"
}
Fail "the Hub from $CopyDir did not answer within 60 s; see $DataDir\logs"
