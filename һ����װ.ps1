$ErrorActionPreference = 'SilentlyContinue'
$host.UI.RawUI.WindowTitle = 'aiyu 环境检查'
Write-Host '============================================'
Write-Host '    aiyu - 环境检查与依赖安装'
Write-Host '============================================'
Write-Host ''
$fail = 0
if (Get-Command python -ErrorAction SilentlyContinue) {
    $v = python --version 2>&1
    Write-Host "[OK] Python   : $v"
} else { Write-Host '[缺少] Python   : 请到 https://www.python.org/downloads/ 安装 3.10+（勾选 Add to PATH）'; $fail++ }
if (Get-Command node -ErrorAction SilentlyContinue) {
    $v = node --version 2>&1
    Write-Host "[OK] Node.js  : $v"
} else { Write-Host '[缺少] Node.js  : 请到 https://nodejs.org 安装 LTS 版'; $fail++ }
$qq = $false
foreach ($p in @('C:\Program Files\Tencent\QQNT\QQ.exe','C:\Program Files (x86)\Tencent\QQNT\QQ.exe')) {
    if (Test-Path $p) { $qq = $true; break }
}
if ($qq) { Write-Host '[OK] QQ NT    : 已安装' } else { Write-Host '[缺少] QQ NT    : 请先安装新版 QQ（https://im.qq.com）并登录一次'; $fail++ }
Write-Host ''
Write-Host '---- 安装 Python 依赖（aiohttp）----'
if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m pip install aiohttp
    if ($LASTEXITCODE -eq 0) { Write-Host '[OK] aiohttp 安装成功' } else { Write-Host '[警告] aiohttp 安装失败，请手动执行: python -m pip install aiohttp' }
}
Write-Host ''
if ($fail -gt 0) { Write-Host "有 $fail 项缺失，按上面提示装好后再回来。" }
else { Write-Host '环境齐全！把 config.example.json 复制为 config.json 并填好，然后双击「启动ai鱼.bat」。' }
Read-Host '按回车关闭'