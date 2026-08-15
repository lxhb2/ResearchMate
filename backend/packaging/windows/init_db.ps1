# init_db.ps1 - Initialize portable PostgreSQL data dir (with pgvector extension)
# Run once on the Windows build machine to produce a ready pgdata directory that
# ships with the portable pack. End users do NOT need to install PostgreSQL.
# (ASCII only - no Chinese to avoid encoding issues)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File init_db.ps1 -PgRoot "C:\pg\postgresql" -PgVectorZip "C:\pg\pgvector-win.zip"
param(
    [Parameter(Mandatory = $true)][string]$PgRoot,       # portable PostgreSQL root (has bin/lib/share)
    [Parameter(Mandatory = $true)][string]$PgVectorZip,  # pgvector windows prebuilt zip
    [string]$DataDir = "..\..\_build\pgdata",            # output data dir
    [string]$DbUser = "researchmate",
    [string]$DbPass = "researchmate",
    [string]$DbName = "researchmate"
)

$ErrorActionPreference = "Stop"
$PgBin    = Join-Path $PgRoot "bin"
$PgLib    = Join-Path $PgRoot "lib"
$PgShare  = Join-Path $PgRoot "share"
$PgDataAbs = Join-Path (Get-Location) $DataDir

Write-Host "[1/5] Checking PostgreSQL binaries..." -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $PgBin "initdb.exe"))) { throw "initdb.exe not found. Point PgRoot at portable PostgreSQL root." }

Write-Host "[2/5] Installing pgvector extension files..." -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP ("pgvector_" + [guid]::NewGuid().ToString("N"))
Expand-Archive -Path $PgVectorZip -DestinationPath $tmp -Force

# Prebuilt package uses extension name "vector" (vector.dll / vector.control / vector--*.sql).
# Also accept legacy naming pgvector.dll / pgvector--*.sql.
$vecDll  = Get-ChildItem -Recurse -Path $tmp -Include "vector.dll","pgvector.dll"            | Select-Object -First 1
$vecCtrl = Get-ChildItem -Recurse -Path $tmp -Include "vector.control","pgvector.control"    | Select-Object -First 1
$vecSqls = Get-ChildItem -Recurse -Path $tmp -Include "vector--*.sql","pgvector--*.sql"
if (-not $vecDll -or -not $vecCtrl -or -not $vecSqls) {
    throw "Required files not found in pgvector zip (vector.dll / vector.control / vector--*.sql)"
}

# Layout: DLL -> lib\; control and sql -> share\extension\; (standard PG extension layout)
# Copy ALL vector--*.sql (base install script + upgrade scripts), not just the first one.
$PgExtDir = Join-Path $PgShare "extension"
New-Item -ItemType Directory -Force -Path $PgExtDir | Out-Null
Copy-Item $vecDll.FullName  -Destination (Join-Path $PgLib   "vector.dll")   -Force
Copy-Item $vecCtrl.FullName -Destination (Join-Path $PgExtDir "vector.control") -Force
foreach ($sql in $vecSqls) {
    Copy-Item $sql.FullName -Destination (Join-Path $PgExtDir $sql.Name) -Force
}
Remove-Item $tmp -Recurse -Force

Write-Host "[3/5] Initializing data dir..." -ForegroundColor Cyan
if (Test-Path $PgDataAbs) { Remove-Item $PgDataAbs -Recurse -Force }
& (Join-Path $PgBin "initdb.exe") -D $PgDataAbs -U postgres -A trust -E UTF8 --encoding=UTF8 | Out-Null

Write-Host "[4/5] Starting temp instance, creating user/db/extension..." -ForegroundColor Cyan
$proc = Start-Process -FilePath (Join-Path $PgBin "postgres.exe") `
    -ArgumentList "-D", $PgDataAbs, "-p", "55432" -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 3
    $env:PGHOST = "127.0.0.1"; $env:PGPORT = "55432"; $env:PGUSER = "postgres"
    $psql = Join-Path $PgBin "psql.exe"
    & $psql -c "CREATE USER $DbUser WITH PASSWORD '$DbPass';"
    & $psql -c "CREATE DATABASE $DbName OWNER $DbUser;"
    & $psql -d $DbName -c "CREATE EXTENSION IF NOT EXISTS vector;"
    & $psql -d $DbName -c "SELECT extname FROM pg_extension;"   # verify
} finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Write-Host "[5/5] Done. Data dir ready: $PgDataAbs" -ForegroundColor Green
Write-Host "        user=$DbUser db=$DbName extension=vector created."