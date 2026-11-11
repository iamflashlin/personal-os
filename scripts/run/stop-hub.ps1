# Stops the always-on Hub's processes (the supervisor and the Hub it started) and waits
# until they are gone. Only processes that are provably ours are touched.
param(
    [string]$CopyDir = "D:\dev\personal-os-run",
    [string]$DataDir = "D:\dev\personal-os-data"
)

$CopyDir = $CopyDir.TrimEnd('\')
$DataDir = $DataDir.TrimEnd('\')
$stopped = @()

# The supervisor first, so it cannot start the Hub again.
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" |
    Where-Object { $_.CommandLine -like "*run-hub.ps1*" -and $_.CommandLine -like "*$CopyDir*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped += $_.ProcessId
    }

# The Hub: uv, and the python it started. A process id from hub.pid is trusted only if that
# process really is `uv ... apps.hub` (ids are reused by Windows); python children running
# from the copy's .venv are found directly too.
$hubs = Get-CimInstance Win32_Process -Filter "Name = 'uv.exe' OR Name = 'python.exe'" |
    Where-Object {
        $_.CommandLine -like "*apps.hub*" -and
        ($_.ExecutablePath -like "$CopyDir\*" -or $_.Name -eq "uv.exe")
    }
$pidFile = Join-Path $DataDir "hub.pid"
$recorded = if (Test-Path $pidFile) { [int](Get-Content $pidFile -Raw) } else { 0 }
foreach ($p in $hubs) {
    $isOurUv = $p.Name -eq "uv.exe" -and $p.ProcessId -eq $recorded
    $isOurPython = $p.Name -eq "python.exe" -and $p.ExecutablePath -like "$CopyDir\*"
    if ($isOurUv -or $isOurPython) {
        # A venv python.exe on Windows is a launcher: the interpreter holding the port and the
        # copy's .pyd files is its child, outside the copy. Remember it so we wait for it too.
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $($p.ProcessId)" |
            ForEach-Object { $stopped += $_.ProcessId }
        & taskkill.exe /PID $p.ProcessId /T /F 2>$null | Out-Null
        $stopped += $p.ProcessId
    }
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue

# Wait, so files under the copy's .venv are no longer locked when the caller goes on.
foreach ($id in $stopped) {
    Wait-Process -Id $id -Timeout 15 -ErrorAction SilentlyContinue
}
