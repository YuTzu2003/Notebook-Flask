param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"

if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env was not found: $envFile"
}

$workerLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^APP_WORKERS=' } |
    Select-Object -Last 1
$workerCount = if ($workerLine) { [int]($workerLine -replace '^APP_WORKERS=', '') } else { 1 }
if ($workerCount -lt 1 -or $workerCount -gt 8) {
    throw "APP_WORKERS must be between 1 and 8."
}

$backendPortLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^BACKEND_BASE_PORT=' } |
    Select-Object -Last 1
$backendBasePort = if ($backendPortLine) { [int]($backendPortLine -replace '^BACKEND_BASE_PORT=', '') } else { 50001 }
$publicPortLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^PUBLIC_HTTP_PORT=' } |
    Select-Object -Last 1
$publicPort = if ($publicPortLine) { [int]($publicPortLine -replace '^PUBLIC_HTTP_PORT=', '') } else { 80 }

$servers = for ($index = 0; $index -lt $workerCount; $index++) {
    "    server 127.0.0.1:$($backendBasePort + $index);"
}
$template = @'
upstream notebook_flask_backend {
__UPSTREAM_SERVERS__
    keepalive 32;
}

server {
    listen __PUBLIC_HTTP_PORT__;
    server_name _;
    client_max_body_size 200m;

    location /static/ {
        alias __PROJECT_ROOT__/static/;
        access_log off;
        expires 7d;
        add_header Cache-Control "public, max-age=604800, immutable";
    }

    location / {
        proxy_pass http://notebook_flask_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_connect_timeout 30s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    location = /health {
        proxy_pass http://notebook_flask_backend/health;
        access_log off;
    }
}
'@

$projectRootForNginx = $projectRoot.Replace('\', '/')
$content = $template.Replace('__UPSTREAM_SERVERS__', ($servers -join [Environment]::NewLine)).Replace('__PROJECT_ROOT__', $projectRootForNginx).Replace('__PUBLIC_HTTP_PORT__', $publicPort)
$configDirectory = Split-Path -Parent $ConfigPath
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
Set-Content -LiteralPath $ConfigPath -Value $content -Encoding utf8
Write-Host "Nginx configuration written to: $ConfigPath"
