param(
    [int]$Port = 50001,
    [switch]$RunScheduler
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
Set-Location -LiteralPath $projectRoot

$envLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match '^APP_ENV=' } | Select-Object -Last 1
if ($envLine -ne "APP_ENV=production") {
    Write-Error "Set APP_ENV=production in .env before starting the production service."
    exit 1
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Python environment not found: $python. Run 'uv sync' first."
    exit 1
}

$env:WAITRESS_HOST = "127.0.0.1"
$env:WAITRESS_PORT = $Port
$env:ENABLE_SCHEDULER = if ($RunScheduler) { "true" } else { "false" }
& $python app.py
exit $LASTEXITCODE
