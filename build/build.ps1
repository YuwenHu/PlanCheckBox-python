# 一键重建 exe（需本机已有 Python 3.10+；脚本会在仓库内建 .venv，不影响系统环境）
# 用法：powershell -ExecutionPolicy Bypass -File build\build.ps1
#      powershell -ExecutionPolicy Bypass -File build\build.ps1 -Onedir   # 改成目录形态

param(
    [switch]$Onedir
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "创建本地虚拟环境 .venv（不会修改系统 Python 环境）..."
    python -m venv $Venv
}

Write-Host "安装/更新打包依赖..."
& $Py -m pip install --disable-pip-version-check -r (Join-Path $Root "requirements.txt")
& $Py -m pip install --disable-pip-version-check -r (Join-Path $Root "build\requirements-build.txt")

Write-Host "运行单元测试..."
& $Py -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw "单元测试未通过，已停止打包" }

$Mode = if ($Onedir) { 'onedir' } else { 'onefile' }
Write-Host "开始打包（$Mode）..."
& $Py -m PyInstaller (Join-Path $Root "build\PlanCheckBox.spec") --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build\.cache")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

if ($Onedir) {
    Write-Host "目录形态产物：dist\PlanCheckBox\PlanCheckBox.exe"
} else {
    Copy-Item -Force (Join-Path $Root "dist\PlanCheckBox.exe") (Join-Path $Root "PlanCheckBox.exe")
    $size = [math]::Round((Get-Item (Join-Path $Root "PlanCheckBox.exe")).Length / 1MB, 1)
    Write-Host "单文件产物：PlanCheckBox.exe（$size MB）"
}

Write-Host "完成。双击 PlanCheckBox.exe 即可启动。"
