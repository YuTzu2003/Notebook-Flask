param(
    [string]$NginxExecutablePath = "C:\nginx\nginx.exe"
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$tasks = Get-ScheduledTask -TaskName "NotebookFlask*" -ErrorAction SilentlyContinue
foreach ($task in $tasks) {
    Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
    Write-Host "Stopped scheduled task: $($task.TaskName)"
}

if ((Get-Process -Name "nginx" -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $NginxExecutablePath)) {
    $nginxDirectory = Split-Path -Parent $NginxExecutablePath
    Push-Location $nginxDirectory
    try {
        & $NginxExecutablePath -s quit
        if ($LASTEXITCODE -ne 0) { throw "Nginx did not stop cleanly." }
        Write-Host "Stopped Nginx."
    }
    finally {
        Pop-Location
    }
}
