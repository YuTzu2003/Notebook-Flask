$ErrorActionPreference = "Stop"

Unregister-ScheduledTask -TaskName "NotebookFlask" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task: NotebookFlask"
