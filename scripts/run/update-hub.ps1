# Updates the always-on Hub to the latest merged code (ADR 0030). Registers nothing.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run\update-hub.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run\update-hub.ps1 -Check
#
# It takes no paths or refs on purpose: the permission rules allow exactly this command, so
# it must not be able to run an unreviewed branch or touch another folder. It always
# deploys origin/main, fetched first (a merge on GitHub does not move the local main).
# -Check runs only the preflight (task, copy, tools, fetch) and stops nothing.
#
# Unlike install-always-on.ps1, this never creates or changes the "PersonalOS Hub" task (the
# user installed it once). It:
# 1. stops the running supervisor and Hub (stop-hub.ps1: only processes proven ours);
# 2. checks that port 8765 is free;
# 3. moves the runtime copy to origin/main, installs packages from the local cache, builds;
#    if any of that fails, moves the copy back to the previous commit and re-syncs it;
# 4. starts the existing task again, and reports success only when the Hub answering on
#    8765 runs from the copy.
# A commit that changes run-hub.ps1's parameters still needs install-always-on.ps1 again.
param([switch]$Check)

$ErrorActionPreference = "Continue"
$CopyDir = "D:\dev\personal-os-run"
$DataDir = "D:\dev\personal-os-data"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$taskName = "PersonalOS Hub"

function Step([string]$text) { Write-Output "== $text" }
function Fail([string]$text) { Unlock-Update $DataDir; Write-Output "FAILED: $text"; exit 1 }

. (Join-Path $PSScriptRoot "update-lock.ps1")  # Lock-Update / Unlock-Update (T-0029)

function Get-Listener {
    $conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($conn.OwningProcess)"
    if (-not $proc) { return $null }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)"
    return [pscustomobject]@{ Proc = $proc; Parent = $parent }
}

function Hub-From-Copy {
    # The listener is this copy's Hub, or the child of its venv launcher (on Windows the
    # interpreter that owns the socket runs from the base Python install).
    $l = Get-Listener
    if (-not $l -or $l.Proc.CommandLine -notlike "*apps.hub*") { return $false }
    if ($l.Proc.ExecutablePath -like "$CopyDir\*") { return $true }
    return $l.Parent -and $l.Parent.ExecutablePath -like "$CopyDir\*"
}

function Build-Copy {
    # Packages from the local cache, then the web page. Returns exactly $true or $false:
    # in PowerShell everything a function writes to the output stream joins its return
    # value, so all progress goes to the host (Out-Host), never to the output stream.
    Push-Location $CopyDir
    try {
        Write-Host "== install Python packages in the copy (from the local cache)"
        & $uv sync --frozen | Out-Host
        if ($LASTEXITCODE -ne 0) { return $false }
        Write-Host "== build the web page in the copy"
        & $pnpm install --frozen-lockfile --prefer-offline | Out-Host
        if ($LASTEXITCODE -ne 0) { return $false }
        & $pnpm --dir apps/web build | Out-Host
        return ($LASTEXITCODE -eq 0)
    } finally {
        Pop-Location
    }
}

Step "preflight"
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    Fail "the '$taskName' task does not exist; run install-always-on.ps1 once first"
}
if (-not (Test-Path (Join-Path $CopyDir ".git"))) {
    Fail "$CopyDir is not a runtime copy; run install-always-on.ps1 once first"
}
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
$pnpm = (Get-Command pnpm -ErrorAction SilentlyContinue).Source
if (-not $uv -or -not $pnpm) { Fail "uv and pnpm must be on PATH" }
git -C $repo fetch --quiet origin main
if ($LASTEXITCODE -ne 0) { Fail "could not fetch origin/main from GitHub" }
$commit = (git -C $repo rev-parse origin/main 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $commit) { Fail "origin/main could not be resolved" }
$commit = $commit.Trim()
$previous = (git -C $CopyDir rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $previous) { Fail "could not read the runtime copy's commit" }
$previous = $previous.Trim()
Write-Output "copy at $($previous.Substring(0, 10)); origin/main is $($commit.Substring(0, 10))"
if ($Check) {
    Write-Output "preflight ok; nothing was stopped or changed"
    exit 0
}

Step "stop the running Hub"
Lock-Update $DataDir
Stop-ScheduledTask -TaskName $taskName
& (Join-Path $PSScriptRoot "stop-hub.ps1") -CopyDir $CopyDir -DataDir $DataDir
$blocker = Get-Listener
if ($blocker) {
    # Something not provably ours holds the port; the Hub could never start. Change nothing.
    Unlock-Update $DataDir
    Start-ScheduledTask -TaskName $taskName
    Fail "port 8765 is in use by pid $($blocker.Proc.ProcessId) $($blocker.Proc.ExecutablePath); stop it first"
}

Step "move the runtime copy to $($commit.Substring(0, 10))"
git -C $CopyDir checkout --quiet --detach $commit
$ok = ($LASTEXITCODE -eq 0) -and (Build-Copy)
if (-not $ok) {
    Step "the update failed; moving the copy back to $($previous.Substring(0, 10))"
    git -C $CopyDir checkout --quiet --detach $previous
    $null = Build-Copy
}

Step "start the Hub again"
Unlock-Update $DataDir
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
        if ($health.status -eq "ok" -and (Hub-From-Copy)) {
            $now = (git -C $CopyDir rev-parse --short HEAD).Trim()
            if (-not $ok) {
                Fail "git could not move the copy, or installing/building failed (see above); the Hub runs the previous commit $now"
            }
            Write-Output "Hub is up: http://127.0.0.1:8765 (commit $now, schema $($health.schema_version))"
            exit 0
        }
    } catch {
        # not up yet
    }
    Start-Sleep -Seconds 2
}
Fail "the Hub from $CopyDir did not answer within 90 s; see $DataDir\logs"
