# Makes the Personal OS Hub always available on this PC (ADR 0021).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run\install-always-on.ps1
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
    [string]$Ref = "HEAD"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$taskName = "PersonalOS Hub"

function Step([string]$text) { Write-Output "== $text" }

$uv = (Get-Command uv -ErrorAction Stop).Source
$pnpm = (Get-Command pnpm -ErrorAction Stop).Source
$commit = (git -C $repo rev-parse $Ref).Trim()

Step "stop the running Hub, if any"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName
}
& (Join-Path $PSScriptRoot "stop-hub.ps1") -DataDir $DataDir

Step "runtime copy at $CopyDir (commit $($commit.Substring(0, 10)))"
if (Test-Path (Join-Path $CopyDir ".git")) {
    git -C $CopyDir checkout --quiet --detach $commit
} else {
    git -C $repo worktree add --detach $CopyDir $commit
}
if ($LASTEXITCODE -ne 0) { throw "git could not prepare $CopyDir" }

Step "install Python packages in the copy (from the local cache)"
Push-Location $CopyDir
try {
    & $uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
    Step "build the web page in the copy"
    & $pnpm install --frozen-lockfile --prefer-offline
    if ($LASTEXITCODE -ne 0) { throw "pnpm install failed" }
    & $pnpm --dir apps/web build
    if ($LASTEXITCODE -ne 0) { throw "web build failed" }
} finally {
    Pop-Location
}

Step "data folder $DataDir"
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null

Step "register the scheduled task '$taskName' (starts at your logon, hidden)"
$runner = Join-Path $CopyDir "scripts\run\run-hub.ps1"
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`" " +
    "-CopyDir `"$CopyDir`" -DataDir `"$DataDir`" -Uv `"$uv`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $CopyDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Personal OS Hub on http://127.0.0.1:8765 (ADR 0021)" -Force | Out-Null

Step "start it now"
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
        if ($health.status -eq "ok") {
            Write-Output "Hub is up: http://127.0.0.1:8765 (schema $($health.schema_version))"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
Write-Output "Hub did not answer within 60 s; see $DataDir\logs\hub.log"
exit 1
