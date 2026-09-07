param(
    [string]$IisSiteName = "NotebookFlask",
    [switch]$OpenDownloadPages
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "prepare-iis.ps1") -OpenDownloadPages:$OpenDownloadPages
& (Join-Path $PSScriptRoot "deploy-production.ps1") -IisSiteName $IisSiteName
