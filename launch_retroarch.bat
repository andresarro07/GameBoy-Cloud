@echo off
cd /d "%~dp0"

echo [SYNC] Pulling latest saves from Cloudflare R2...
python sync.py pull
if errorlevel 1 (
    echo [WARNING] Cloud pull failed. Check your internet connection.
    pause
)

echo [LAUNCH] Starting RetroArch...
start "" /wait "C:\RetroArch-Win64\retroarch.exe"

echo [SYNC] Pushing updated saves to Cloudflare R2...
python sync.py push
if errorlevel 1 (
    echo [ERROR] Cloud push failed! Your save is only stored locally.
    pause
)