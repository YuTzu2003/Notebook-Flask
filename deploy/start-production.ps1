$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$envLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match '^APP_ENV=' } | Select-Object -Last 1
if ($envLine -ne "APP_ENV=production") {
    Write-Error "Set APP_ENV=production in .env before starting the production service."
    exit 1
}

& uv run python app.py
exit $LASTEXITCODE
