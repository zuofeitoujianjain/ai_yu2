$ErrorActionPreference = 'SilentlyContinue'
if ($env:AIYU_ROOT) { $root = $env:AIYU_ROOT.TrimEnd('\') } else { $root = (Get-Location).Path }
$napcatDir = Join-Path $root 'napcat'
$host.UI.RawUI.WindowTitle = 'aiyu 一键启动'
Write-Host '============================================'
Write-Host '    aiyu - QQ群AI机器人 一键启动器'
Write-Host "    目录：$root"
Write-Host '============================================'
Write-Host ''
if (-not (Test-Path (Join-Path $root 'bot.py'))) {
    Write-Host "[错误] 找不到 bot.py：$root"
    Read-Host '按回车退出'
    exit 1
}
if (-not (Test-Path (Join-Path $napcatDir 'launcher-user.bat'))) {
    Write-Host "[错误] 找不到 NapCat：请把 NapCat Shell 解压到 $napcatDir（含 launcher-user.bat）"
    Read-Host '按回车退出'
    exit 1
}
$napcatOn = Get-NetTCPConnection -LocalPort 6099 -State Listen -ErrorAction SilentlyContinue
if ($napcatOn) {
    Write-Host '[1/3] NapCat 已在运行，跳过启动'
} else {
    Write-Host '[1/3] 启动 NapCat（会弹出 QQ 窗口，首次使用需扫码登录）...'
    try {
        Start-Process cmd.exe -WorkingDirectory $napcatDir -ArgumentList '/k','(title NapCat) && chcp 65001 >nul && call launcher-user.bat' -ErrorAction Stop
    } catch { Write-Host "[错误] 启动 NapCat 失败：$_" }
}
Write-Host '[2/3] 等待 NapCat 的 WebSocket 服务就绪...'
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    if (Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Host '    提示：还没就绪（多半是 QQ 还没登录/扫码），机器人稍后会自己连上' }
Write-Host '[3/3] 启动 AI 机器人...'
try {
    Start-Process cmd.exe -WorkingDirectory $root -ArgumentList '/k','(title ai鱼机器人) && chcp 65001 >nul && python bot.py' -ErrorAction Stop
} catch { Write-Host "[错误] 启动机器人失败：$_" }
Write-Host ''
Write-Host '============================================'
Write-Host '  启动完成！请保持 NapCat、ai鱼机器人 两个窗口开着'
Write-Host '  停止请运行：停止ai鱼.bat'
Write-Host '============================================'
Start-Sleep -Seconds 3