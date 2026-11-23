@echo off
setlocal

:: Switch to the directory where this script (and .env / sync.py) lives

cd /d "%~dp0"
"venv\Scripts\python.exe" sync.py pull
start "" /wait "C:\RetroArch-Win64\retroarch.exe"
"venv\Scripts\python.exe" sync.py push
timeout /t 3 >nul