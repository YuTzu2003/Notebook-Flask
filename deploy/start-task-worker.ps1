$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "tasks\logs"
$logFile = Join-Path $logDirectory "notebook-flask-task-worker.log"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python. Run 'uv sync' first."
}

$envLine = Get-Content -LiteralPath (Join-Path $projectRoot ".env") |
    Where-Object { $_ -match '^APP_ENV=' } |
    Select-Object -Last 1
if ($envLine -ne "APP_ENV=production") {
    throw "Set APP_ENV=production in .env before starting the task worker."
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location -LiteralPath $projectRoot
Start-Sleep -Seconds 30
$env:ENABLE_SCHEDULER = "false"
& $python -m modules.task_queue *>> $logFile
exit $LASTEXITCODE
