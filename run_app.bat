@echo off
cd /d C:\Users\imkjh\stock-alert

echo Starting Stock Signal App...
echo Browser : http://localhost:8501
echo Mobile  : http://192.168.0.8:8501
echo.
echo Press Ctrl+C to stop.
echo.

venv\Scripts\streamlit.exe run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false
