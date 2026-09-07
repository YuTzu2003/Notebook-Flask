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
