@echo off
cd /d "%~dp0"
set FLASK_ENV=development
echo Starting server at http://127.0.0.1:5000
python run.py
pause
