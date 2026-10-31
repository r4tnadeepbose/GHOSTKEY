@echo off
rem Launch Ghostkey using the project virtualenv when available.
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scan.py
) else (
    python scan.py
)
endlocal
