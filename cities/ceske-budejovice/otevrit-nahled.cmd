@echo off
setlocal
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -X utf8 "scripts\open_cb_review.py"
if errorlevel 1 pause
