$ErrorActionPreference = "Stop"

$tasks = Get-ScheduledTask -TaskName "NotebookFlask*" -ErrorAction SilentlyContinue
foreach ($task in $tasks) {
    Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
    Write-Host "Removed scheduled task: $($task.TaskName)"
}
