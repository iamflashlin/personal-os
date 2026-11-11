# Removes the always-on Hub (ADR 0021). Data stays; the code copy stays unless asked.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run\uninstall-always-on.ps1 [-RemoveCopy]
param(
    [string]$CopyDir = "D:\dev\personal-os-run",
    [string]$DataDir = "D:\dev\personal-os-data",
    [switch]$RemoveCopy
)

$taskName = "PersonalOS Hub"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "removed the scheduled task '$taskName'"
}
& (Join-Path $PSScriptRoot "stop-hub.ps1") -DataDir $DataDir
Write-Output "stopped the Hub; your data is still in $DataDir"
if ($RemoveCopy -and (Test-Path $CopyDir)) {
    $repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    git -C $repo worktree remove --force $CopyDir
    Write-Output "removed the code copy at $CopyDir"
}
