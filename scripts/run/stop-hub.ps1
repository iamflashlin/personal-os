# Stops the always-on Hub's processes (the supervisor and the Hub it started).
param([string]$DataDir = "D:\dev\personal-os-data")

$pidFile = Join-Path $DataDir "hub.pid"
# The supervisor first, so it cannot start the Hub again.
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like "*run-hub.ps1*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if (Test-Path $pidFile) {
    $hubPid = [int](Get-Content $pidFile -Raw)
    # uv starts python as a child: stop the whole tree.
    & taskkill.exe /PID $hubPid /T /F 2>$null | Out-Null
    Remove-Item $pidFile -Force
}
