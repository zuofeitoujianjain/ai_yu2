$ErrorActionPreference = 'SilentlyContinue'
$host.UI.RawUI.WindowTitle = 'aiyu 一键停止'
Write-Host '============================================'
Write-Host '    aiyu - 一键停止（机器人 + NapCat + QQ）'
Write-Host '============================================'
Write-Host ''
Get-NetTCPConnection -RemotePort 3001 -State Established -ErrorAction SilentlyContinue |
    Where-Object { $_.RemoteAddress -in @('127.0.0.1','::1') } |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Write-Host '[1/3] AI 机器人已停止'
Get-NetTCPConnection -LocalPort 6099 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Write-Host '[2/3] NapCat 已停止'
taskkill /F /IM NapCatWinBootMain.exe 2>$null | Out-Null
taskkill /F /FI "WINDOWTITLE eq NapCat*" 2>$null | Out-Null
taskkill /F /FI "WINDOWTITLE eq ai鱼机器人*" 2>$null | Out-Null
Write-Host '[3/3] 收尾完成'
Write-Host ''
Write-Host '全部已停止。下次启动请运行：启动ai鱼.bat'
Read-Host '按回车关闭'