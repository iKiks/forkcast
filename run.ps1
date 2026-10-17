# Forkcast quick start for Windows PowerShell.
# Usage:  .\run.ps1          (first run creates .venv and installs dependencies)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}
Write-Host "Forkcast is starting at http://127.0.0.1:8000  (Ctrl+C to stop)"
Start-Process "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m uvicorn forkcast.server:app --host 127.0.0.1 --port 8000
