param(
    [Parameter(Mandatory = $true)]
    [string]$SiteName,
    [Parameter(Mandatory = $true)]
    [int]$PublicPort
)

$ErrorActionPreference = "Stop"

Import-Module WebAdministration
if (-not (Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue)) {
    throw "IIS URL Rewrite is not installed. Install URL Rewrite and ARR before deployment."
}

function Invoke-AppCmd {
    param(
        [string[]]$Arguments,
        [switch]$IgnoreFailure
    )

    $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    if ($IgnoreFailure) {
        & $appCmd @Arguments 2>$null | Out-Null
        return
    }
    & $appCmd @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "appcmd failed: $($Arguments -join ' ')"
    }
}

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

try {
    Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "enabled" -Value "True"
}
catch {
    throw "IIS Application Request Routing (ARR) is not installed. Install ARR and URL Rewrite before deployment."
}

$siteRoot = Join-Path $PSScriptRoot "iis-proxy"
New-Item -ItemType Directory -Path $siteRoot -Force | Out-Null
$webConfig = @'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="Serve static files directly" stopProcessing="true">
          <match url="^static/.*" />
          <action type="None" />
        </rule>
        <rule name="Reverse proxy to Notebook Flask" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://NotebookFlaskBackend/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
  <location path="static">
    <system.webServer>
      <staticContent>
        <clientCache cacheControlMode="UseMaxAge" cacheControlMaxAge="7.00:00:00" />
      </staticContent>
    </system.webServer>
  </location>
</configuration>
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $siteRoot "web.config"), $webConfig, $utf8NoBom)

$sitePath = "IIS:\Sites\$SiteName"
if (-not (Test-Path -LiteralPath $sitePath)) {
    $bindingInUse = Get-WebBinding | Where-Object {
        $_.protocol -eq "http" -and $_.bindingInformation -match (":${PublicPort}:$")
    }
    if ($bindingInUse) {
        throw "HTTP port $PublicPort is already bound by IIS site '$($bindingInUse.ItemXPath)'. Choose an unused PUBLIC_HTTP_PORT."
    }
    New-Website -Name $SiteName -PhysicalPath $siteRoot -Port $PublicPort | Out-Null
}
else {
    Set-ItemProperty -LiteralPath $sitePath -Name physicalPath -Value $siteRoot
    if (-not (Get-WebBinding -Name $SiteName -Protocol "http" | Where-Object { $_.bindingInformation -match (":${PublicPort}:$") })) {
        New-WebBinding -Name $SiteName -Protocol "http" -Port $PublicPort
    }
}

$staticPath = "$sitePath/static"
if (Test-Path -LiteralPath $staticPath) {
    Set-ItemProperty -LiteralPath $staticPath -Name physicalPath -Value (Join-Path $projectRoot "static")
}
else {
    New-WebVirtualDirectory -Site $SiteName -Name "static" -PhysicalPath (Join-Path $projectRoot "static") | Out-Null
}

Invoke-AppCmd -Arguments @("set", "config", "-section:webFarms", "/-`"[name='NotebookFlaskBackend']`"", "/commit:apphost") -IgnoreFailure
Invoke-AppCmd -Arguments @("set", "config", "-section:webFarms", "/+`"[name='NotebookFlaskBackend']`"", "/commit:apphost")
for ($index = 0; $index -lt $workerCount; $index++) {
    $address = "127.0.0.$($index + 1)"
    $port = $backendBasePort + $index
    Invoke-AppCmd -Arguments @("set", "config", "-section:webFarms", "/+`"[name='NotebookFlaskBackend'].[address='$address']`"", "/commit:apphost")
    Invoke-AppCmd -Arguments @("set", "config", "-section:webFarms", "/[name='NotebookFlaskBackend'].[address='$address'].applicationRequestRouting.httpPort:$port", "/commit:apphost")
}

Write-Host "Configured IIS site '$SiteName' on port $PublicPort with $workerCount ARR backend server(s)."
