param(
    [string]$NginxExecutablePath = "C:\nginx\nginx.exe"
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$startupScript = Join-Path $PSScriptRoot "start-on-boot.ps1"
$taskWorkerScript = Join-Path $PSScriptRoot "start-task-worker.ps1"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $startupScript)) {
    throw "Startup script not found: $startupScript"
}
if (-not (Test-Path -LiteralPath $taskWorkerScript)) {
    throw "Task worker script not found: $taskWorkerScript"
}
if (-not (Test-Path -LiteralPath $NginxExecutablePath)) {
    throw "nginx.exe was not found: $NginxExecutablePath"
}

$workerLine = Get-Content -LiteralPath (Join-Path $projectRoot ".env") |
    Where-Object { $_ -match '^APP_WORKERS=' } |
    Select-Object -Last 1
$workerCount = if ($workerLine) { [int]($workerLine -replace '^APP_WORKERS=', '') } else { 1 }
if ($workerCount -lt 1 -or $workerCount -gt 8) {
    throw "APP_WORKERS must be between 1 and 8."
}
$backendPortLine = Get-Content -LiteralPath (Join-Path $projectRoot ".env") |
    Where-Object { $_ -match '^BACKEND_BASE_PORT=' } |
    Select-Object -Last 1
$backendBasePort = if ($backendPortLine) { [int]($backendPortLine -replace '^BACKEND_BASE_PORT=', '') } else { 50001 }

Unregister-ScheduledTask -TaskName "NotebookFlask" -Confirm:$false -ErrorAction SilentlyContinue
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$settings.ExecutionTimeLimit = "PT0S"
$settings.RestartCount = 3
$settings.RestartInterval = "PT1M"
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

for ($index = 0; $index -lt $workerCount; $index++) {
    $port = $backendBasePort + $index
    $taskName = "NotebookFlask-{0:D2}" -f ($index + 1)
    $schedulerArgument = if ($index -eq 0) { " -RunScheduler" } else { "" }
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Port {1}{2}' -f $startupScript, $port, $schedulerArgument
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $taskPrincipal -Description "Starts Notebook Flask worker on port $port." -Force | Out-Null
    Write-Host "Registered scheduled task: $taskName"
}

$taskWorkerAction = New-ScheduledTaskAction -Execute $powershell -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $taskWorkerScript)
Register-ScheduledTask -TaskName "NotebookFlaskTaskWorker" -Action $taskWorkerAction -Trigger $trigger -Settings $settings -Principal $taskPrincipal -Description "Processes queued PDF mapping and migration tasks." -Force | Out-Null
Write-Host "Registered scheduled task: NotebookFlaskTaskWorker"

$nginxDirectory = Split-Path -Parent $NginxExecutablePath
$nginxAction = New-ScheduledTaskAction -Execute $NginxExecutablePath -WorkingDirectory $nginxDirectory
Register-ScheduledTask -TaskName "NotebookFlaskNginx" -Action $nginxAction -Trigger $trigger -Settings $settings -Principal $taskPrincipal -Description "Starts Nginx for Notebook Flask." -Force | Out-Null
Write-Host "Registered scheduled task: NotebookFlaskNginx"
