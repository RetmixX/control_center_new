@echo off
rem Desktop-версия для Windows
cd /d "%~dp0"
if not exist venv-desktop (python -m venv venv-desktop && venv-desktop\Scripts\pip install -q -r requirements-desktop.txt)
start "" venv-desktop\Scripts\pythonw -m controlcenter.desktop --dir . %*
