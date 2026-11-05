@echo off
rem CLI-версия для Windows
cd /d "%~dp0"
if not exist venv (python -m venv venv && venv\Scripts\pip install -q -r requirements.txt)
venv\Scripts\python -m controlcenter --dir . %*
