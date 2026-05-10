param(
    [int]$Port = 8958
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dashboard = Join-Path $Root "archive\dashboard"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Dashboard)) {
    throw "未找到 dashboard 目录：$Dashboard。请先运行：.\.venv\Scripts\python.exe -m qq_valhalla dashboard"
}

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Serving $Dashboard"
Write-Host "Open http://127.0.0.1:$Port/latest.html"
& $Python -m http.server $Port --directory $Dashboard
