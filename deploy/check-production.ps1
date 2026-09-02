$ErrorActionPreference = "Stop"

function Get-EnvironmentValue {
    param(
        [string]$Path,
        [string]$Name
    )

    $line = Get-Content -LiteralPath $Path |
        Where-Object { $_ -match ("^{0}=" -f [regex]::Escape($Name)) } |
        Select-Object -Last 1
    if ($line) {
        return $line.Substring($Name.Length + 1)
    }
    return ""
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env was not found: $envFile"
}

$publicPort = Get-EnvironmentValue -Path $envFile -Name "PUBLIC_HTTP_PORT"
$backendPort = Get-EnvironmentValue -Path $envFile -Name "BACKEND_BASE_PORT"
$healthUri = "http://127.0.0.1:{0}/health" -f $backendPort

Write-Host "Backend health: $healthUri"
try {
    Invoke-RestMethod -Uri $healthUri -TimeoutSec 3 -ErrorAction Stop | ConvertTo-Json -Compress
}
catch {
    Write-Host "Backend is unavailable: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "Public URL: http://<server-ip>:$publicPort/"
Get-ScheduledTask -TaskName "NotebookFlask*" -ErrorAction SilentlyContinue |
    Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName "NotebookFlask-01" -ErrorAction SilentlyContinue |
    Select-Object LastRunTime, LastTaskResult
