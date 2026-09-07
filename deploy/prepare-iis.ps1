param(
    [switch]$OpenDownloadPages
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

try {
    Import-Module WebAdministration -ErrorAction Stop
}
catch {
    throw "IIS with Management Tools is not installed. Install IIS manually, then run this script again."
}
$rewriteInstalled = [bool](Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue)
$arrInstalled = $false
try {
    Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "enabled" -ErrorAction Stop | Out-Null
    $arrInstalled = $true
}
catch {
}

if (-not $rewriteInstalled -or -not $arrInstalled) {
    Write-Host "Install IIS URL Rewrite 2.1 and IIS ARR 3.0, then run this script again." -ForegroundColor Yellow
    Write-Host "URL Rewrite: https://www.iis.net/downloads/microsoft/url-rewrite"
    Write-Host "ARR: https://www.iis.net/downloads/microsoft/application-request-routing"
    if ($OpenDownloadPages) {
        Start-Process "https://www.iis.net/downloads/microsoft/url-rewrite"
        Start-Process "https://www.iis.net/downloads/microsoft/application-request-routing"
    }
    throw "IIS URL Rewrite and ARR must be installed before deployment."
}

Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "enabled" -Value "True"
Write-Host "IIS, URL Rewrite, and ARR are ready. ARR reverse proxy is enabled."
