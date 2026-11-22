# Lets the always-on Hub keep the desktop agent running (T-0063, ADR 0043).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run\enable-agent.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run\enable-agent.ps1 -Disable
#
# Enable: asks the running Hub for a one-time pairing code, pairs the agent in the runtime
# copy (its token goes to Windows Credential Manager, never to a file), then writes
# agent.enabled in the data folder. The supervisor (run-hub.ps1) starts the agent within a
# few seconds and starts it again if it ever stops. Running it again re-pairs.
# -Disable: removes agent.enabled; the supervisor stops the agent. The pairing stays.
#
# Registers nothing with Windows: the agent runs under the existing "PersonalOS Hub" task.
param(
    [switch]$Disable,
    [string]$CopyDir = "D:\dev\personal-os-run",
    [string]$DataDir = "D:\dev\personal-os-data",
    [string]$HubUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Continue"
# Chinese messages: print UTF-8 also when the output is piped (and in an older console).
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$CopyDir = $CopyDir.TrimEnd('\')
$DataDir = $DataDir.TrimEnd('\')
$flag = Join-Path $DataDir "agent.enabled"

function Get-Online {
    try { return [bool](Invoke-RestMethod -Uri "$HubUrl/agent/status" -TimeoutSec 3).online }
    catch { return $false }
}

function Wait-Online([bool]$want, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-Online) -eq $want) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

if ($Disable) {
    Remove-Item $flag -Force -ErrorAction SilentlyContinue
    if (Wait-Online $false 20) {
        Write-Output "电脑助手已停止（以后不会自动启动；要再打开就不加 -Disable 运行一次）"
        exit 0
    }
    Write-Output "FAILED: 电脑助手 20 秒内没有停下，看 $DataDir\logs\hub.log"
    exit 1
}

try {
    $health = Invoke-RestMethod -Uri "$HubUrl/health" -TimeoutSec 5
} catch {
    Write-Output "FAILED: Hub 没有在 $HubUrl 回应；先确认 Hub 在运行"
    exit 1
}
if ($health.status -ne "ok") { Write-Output "FAILED: Hub 状态不对：$($health.status)"; exit 1 }

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { Write-Output "FAILED: 找不到 uv"; exit 1 }
if (-not (Test-Path (Join-Path $CopyDir "apps\desktop_agent"))) {
    Write-Output "FAILED: $CopyDir 里没有电脑助手的代码；先运行 update-hub.ps1"
    exit 1
}

# Stop a running supervised agent first, so the new token is the one that connects.
Remove-Item $flag -Force -ErrorAction SilentlyContinue
$null = Wait-Online $false 15

Write-Output "== 向 Hub 要一次性配对码"
try {
    $code = (Invoke-RestMethod -Method Post -Uri "$HubUrl/devices/pairing-codes" -TimeoutSec 5).code
} catch {
    Write-Output "FAILED: Hub 没有给配对码：$($_.Exception.Message)"
    exit 1
}

Write-Output "== 配对电脑助手（令牌存进 Windows 凭据管理器）"
Push-Location $CopyDir
& $uv run --frozen python -m apps.desktop_agent --hub-url $HubUrl pair --code $code
$paired = $LASTEXITCODE -eq 0
Pop-Location
if (-not $paired) { Write-Output "FAILED: 配对没有成功（见上面）"; exit 1 }

Write-Output "== 打开常驻开关"
Set-Content -Path $flag -Value (Get-Date -Format o) -Encoding ascii
if (Wait-Online $true 30) {
    Write-Output "电脑助手已连上，会跟 Hub 一起常驻（开机也会自动启动）"
    exit 0
}
Write-Output "FAILED: 30 秒内电脑助手没有连上 Hub；看 $DataDir\logs\agent-run-*-err.log"
exit 1
