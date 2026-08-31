$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "tasks\logs"
$logFile = Join-Path $logDirectory "notebook-flask.log"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python. Run 'uv sync' first."
}

$envLine = Get-Content -LiteralPath (Join-Path $projectRoot ".env") |
    Where-Object { $_ -match '^APP_ENV=' } |
    Select-Object -Last 1
if ($envLine -ne "APP_ENV=production") {
    throw "Set APP_ENV=production in .env before enabling automatic startup."
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location -LiteralPath $projectRoot

# Allow local SQL Server, network, and Nginx services to finish booting.
Start-Sleep -Seconds 30
& $python app.py *>> $logFile
exit $LASTEXITCODE
