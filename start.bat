@echo off
cd /d "%~dp0"
echo Starting VoteSafe at http://localhost:8000
python server.py
pause
