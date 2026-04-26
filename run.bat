@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\Users\imkjh\stock-alert
venv\Scripts\python.exe main.py >> logs\run_%date:~0,4%%date:~5,2%%date:~8,2%.log 2>&1
