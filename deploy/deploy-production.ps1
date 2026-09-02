param(
    [string]$NginxExecutablePath = "C:\nginx\nginx.exe"
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required program was not found in PATH: $Name"
    }
}

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

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

Require-Command "uv"

$driver18 = Test-Path "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server"
$driver17 = Test-Path "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server"
if (-not $driver18 -and -not $driver17) {
    throw "ODBC Driver 17 or 18 for SQL Server was not found. Install it before deployment."
}
if (-not (Test-Path -LiteralPath $NginxExecutablePath)) {
    throw "nginx.exe was not found: $NginxExecutablePath"
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    throw "Created .env from .env.example. Set DATABASE_URL and production settings in .env, then run deployment again."
}

$databaseUrl = Get-EnvironmentValue -Path $envFile -Name "DATABASE_URL"
if ([string]::IsNullOrWhiteSpace($databaseUrl) -or $databaseUrl -match 'user:password') {
    throw "Set a valid DATABASE_URL in .env before deployment."
}
$appEnvironment = Get-EnvironmentValue -Path $envFile -Name "APP_ENV"
$secretKey = Get-EnvironmentValue -Path $envFile -Name "SECRET_KEY"
if ($appEnvironment -ne "production") {
    throw "Set APP_ENV=production in .env before deployment."
}
if ([string]::IsNullOrWhiteSpace($secretKey) -or $secretKey -eq "development-only-change-before-production") {
    throw "Set a new SECRET_KEY in .env before deployment."
}
if ($databaseUrl -match 'ODBC\+Driver\+18' -and -not $driver18) {
    throw "DATABASE_URL requires ODBC Driver 18, but it is not installed."
}
if ($databaseUrl -match 'ODBC\+Driver\+17' -and -not $driver17) {
    throw "DATABASE_URL requires ODBC Driver 17, but it is not installed."
}
$publicPort = [int](Get-EnvironmentValue -Path $envFile -Name "PUBLIC_HTTP_PORT")
if ($publicPort -lt 1 -or $publicPort -gt 65535) {
    throw "PUBLIC_HTTP_PORT in .env must be between 1 and 65535."
}

Set-Location -LiteralPath $projectRoot
& uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }

& uv run python .\deploy\init_database.py
if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }

$nginxDirectory = Split-Path -Parent $NginxExecutablePath
$nginxConfigDirectory = Join-Path $nginxDirectory "conf"
$nginxConfig = Join-Path $nginxConfigDirectory "nginx.conf"
$siteConfig = Join-Path $nginxConfigDirectory "notebook_flask.conf"
if (-not (Test-Path -LiteralPath $nginxConfig)) {
    throw "Nginx configuration was not found: $nginxConfig"
}

& (Join-Path $PSScriptRoot "configure-nginx.ps1") -ConfigPath $siteConfig
$nginxContent = Get-Content -LiteralPath $nginxConfig -Raw
if ($nginxContent -notmatch '(?m)^\s*include\s+notebook_flask\.conf;') {
    if ($nginxContent -notmatch '(?m)^http\s*\{') {
        throw "Could not find the http block in: $nginxConfig"
    }
    $nginxContent = $nginxContent -replace '(?m)^http\s*\{', "http {`r`n    include notebook_flask.conf;"
    Set-Content -LiteralPath $nginxConfig -Value $nginxContent -Encoding utf8
}

Push-Location $nginxDirectory
try {
    & $NginxExecutablePath -t
    if ($LASTEXITCODE -ne 0) { throw "Nginx configuration validation failed." }
    if (Get-Process -Name "nginx" -ErrorAction SilentlyContinue) {
        & $NginxExecutablePath -s reload
    }
    else {
        Start-Process -FilePath $NginxExecutablePath -WorkingDirectory $nginxDirectory
    }
}
finally {
    Pop-Location
}

Get-NetFirewallRule -DisplayName "Notebook Flask HTTP" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Notebook Flask HTTP" -Direction Inbound -Protocol TCP -LocalPort $publicPort -Action Allow | Out-Null

& (Join-Path $PSScriptRoot "register-autostart.ps1") -NginxExecutablePath $NginxExecutablePath
Start-ScheduledTask -TaskName "NotebookFlask-01"
Start-ScheduledTask -TaskName "NotebookFlaskTaskWorker"

Write-Host "Deployment completed. Wait about 30 seconds for the backend startup, then open http://<server-ip>/"
