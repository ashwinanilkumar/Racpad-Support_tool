@echo off
REM Start the Flask app in a new window and open the browser (Windows)
SETLOCAL
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run setup.bat first.
  pause
  exit /b 1
)

echo Starting Flask server in a new window...
start "" ".venv\Scripts\python.exe" "flask_app.py"

REM Give the server a moment to start then open the default browser
timeout /t 2 >nul
echo Opening browser to http://127.0.0.1:8501
start "" "http://127.0.0.1:8501"

ENDLOCAL
