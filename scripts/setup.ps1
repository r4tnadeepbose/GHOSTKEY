#requires -Version 5.1
<#
.SYNOPSIS
    Create a virtual environment and install Ghostkey dependencies.

.DESCRIPTION
    Run from the repository root or from anywhere; the script resolves the
    project root relative to its own location.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python not found on PATH. Install Python 3.10+ and retry."
}
$version = & python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "ghostkey :: setup" -ForegroundColor Yellow
Write-Host "  python $version at $($python.Source)"

if (-not (Test-Path '.venv')) {
    Write-Host "  creating .venv"
    & python -m venv .venv
}

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt

Write-Host ""
Write-Host "done. launch with:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python.exe scan.py"
