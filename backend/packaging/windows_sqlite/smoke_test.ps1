param(
    [int]$Port = 18181
)

$ErrorActionPreference = "Stop"
$exe = Join-Path $PSScriptRoot "dist\ResearchMate.exe"
$run = Join-Path $PSScriptRoot "build\smoke-run"

New-Item -ItemType Directory -Force -Path $run | Out-Null

$env:PORT = "$Port"
$env:HOST = "127.0.0.1"
$env:STORAGE_DIR = Join-Path $run "storage"
$env:PDF_DIR = Join-Path $run "storage\pdfs"
$env:DATABASE_URL = "sqlite:///" + ((Join-Path $run "researchmate.db") -replace "\\", "/")

$process = Start-Process -FilePath $exe -WorkingDirectory $run -WindowStyle Hidden -PassThru
try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/v1/app/info" -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Write-Output $response.Content
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    if (-not $ready) {
        throw "packaged backend did not become ready"
    }
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
}
