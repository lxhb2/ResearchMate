$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = (Get-Command py -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    $Python = "python"
}

if (-not (Test-Path ".venv-pdf2zh")) {
    & $Python -m venv ".venv-pdf2zh"
}

& ".venv-pdf2zh\Scripts\python.exe" -m pip install --upgrade pip
& ".venv-pdf2zh\Scripts\python.exe" -m pip install -r "requirements-pdf2zh.txt"

Write-Host ""
Write-Host "pdf2zh-next 隔离环境已就绪：$Root\.venv-pdf2zh"
Write-Host "整篇翻译会自动优先使用 pdf2zh-next，失败时回退 BabelDOC。"
