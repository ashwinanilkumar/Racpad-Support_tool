@echo off
REM Create venv and install dependencies (Windows)
SETLOCAL
if exist .venv ( 
  echo Virtual environment already exists, skipping creation.
) else (
  echo Creating virtual environment...
  python -m venv .venv
)

echo Activating virtual environment and installing requirements...
.venv\Scripts\pip.exe install --upgrade pip
if exist requirements.txt (
  .venv\Scripts\pip.exe install -r requirements.txt
  if errorlevel 1 (
    echo ERROR: Failed to install one or more dependencies.
    echo Check your internet connection and the contents of requirements.txt.
    pause
    exit /b 1
  )
) else (
  echo requirements.txt not found, skipping dependency install.
)

echo Setup complete. To run the app use run.bat
ENDLOCAL
pause
