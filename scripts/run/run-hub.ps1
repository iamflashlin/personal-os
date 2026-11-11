# Keeps the Personal OS Hub running: starts it, and starts it again if it ever exits.
# Started at logon by the "PersonalOS Hub" scheduled task (install-always-on.ps1).
param(
    [Parameter(Mandatory = $true)][string]$CopyDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [Parameter(Mandatory = $true)][string]$Uv
)

$ErrorActionPreference = "Continue"
$logs = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs "hub.log"
$pidFile = Join-Path $DataDir "hub.pid"

function Write-Log([string]$text) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $log -Value "$stamp supervisor: $text" -Encoding utf8
}

$env:POS_DATA_DIR = $DataDir
$env:PYTHONIOENCODING = "utf-8"
Set-Location $CopyDir

while ($true) {
    # Keep the log small: one previous file is kept.
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 10MB)) {
        Move-Item -Force $log "$log.1"
    }
    Write-Log "starting Hub from $CopyDir with data_dir=$DataDir"
    $proc = Start-Process -FilePath $Uv -ArgumentList @("run", "--frozen", "python", "-m", "apps.hub") `
        -WorkingDirectory $CopyDir -NoNewWindow -PassThru `
        -RedirectStandardOutput "$log.out" -RedirectStandardError "$log.err"
    Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
    $proc.WaitForExit()
    foreach ($part in @("$log.out", "$log.err")) {
        if (Test-Path $part) {
            Get-Content $part -Encoding utf8 | Add-Content -Path $log -Encoding utf8
            Remove-Item $part -Force
        }
    }
    Write-Log "Hub exited with code $($proc.ExitCode); starting again in 10 s"
    Start-Sleep -Seconds 10
}
