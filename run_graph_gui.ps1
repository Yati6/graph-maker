# Starts graph_gui.py with the same Python as .vscode/settings.json (non-Store install).
$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Python not found at: $py`nInstall from https://www.python.org/downloads/ or edit this script to match your install."
    exit 1
}
Set-Location $PSScriptRoot
& $py graph_gui.py @args
