# WholesaleOS local launcher — always runs from the correct folder.
# Usage: right-click run.ps1 → Run with PowerShell   (or: .\run.ps1)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $here

$streamlit = Join-Path $here "venv\Scripts\streamlit.exe"
if (-Not (Test-Path $streamlit)) {
    Write-Host "ERROR: venv not found. Run: python -m venv venv; venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

Write-Host "Starting WholesaleOS at http://localhost:8501 ..." -ForegroundColor Cyan
& $streamlit run "app\main.py"
