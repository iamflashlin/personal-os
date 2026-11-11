# Removes the always-on Hub (ADR 0021). Data stays; the code copy stays unless asked.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run\uninstall-always-on.ps1 [-RemoveCopy]
param(
    [string]$CopyDir = "D:\dev\personal-os-run",
    [string]$DataDir = "D:\dev\personal-os-data",
    [switch]$RemoveCopy
)

$CopyDir = $CopyDir.TrimEnd('\')
$DataDir = $DataDir.TrimEnd('\')
$taskName = "PersonalOS Hub"
if ($RemoveCopy -and $DataDir -like "$CopyDir\*") {
    Write-Output "FAILED: -DataDir is inside -CopyDir; refusing -RemoveCopy so no data is lost"
    exit 1
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Write-Output "FAILED: the scheduled task '$taskName' is still there"
        exit 1
    }
    Write-Output "removed the scheduled task '$taskName'"
}
& (Join-Path $PSScriptRoot "stop-hub.ps1") -CopyDir $CopyDir -DataDir $DataDir
Write-Output "stopped the Hub; your data is still in $DataDir"
if ($RemoveCopy -and (Test-Path $CopyDir)) {
    $repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    git -C $repo worktree remove --force $CopyDir
    if ($LASTEXITCODE -ne 0) {
        Write-Output "FAILED: could not remove $CopyDir (files may still be in use)"
        exit 1
    }
    Write-Output "removed the code copy at $CopyDir"
}
