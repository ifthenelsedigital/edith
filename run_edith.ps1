# Start EDITH from its own virtual environment.
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
& .\venv\Scripts\python.exe main.py
