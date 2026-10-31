#requires -Version 5.1
# Launch Ghostkey using the project virtualenv when available.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path $venvPy) {
    & $venvPy scan.py
} else {
    & python scan.py
}
