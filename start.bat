@echo off
rem One-click NeuroGrip launcher. Uses NVIDIA_API_KEY / GEMINI_API_KEY / MONGODB_URI from your user environment.
rem Mode: double-click = camera mode. For others:  start.bat mock   or   start.bat hardware COM5
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Python environment...
  py -3.10 -m venv .venv || goto :fail
  ".venv\Scripts\pip" install -r requirements.txt || goto :fail
)
set "NG_MODE=%~1"
if "%NG_MODE%"=="" set "NG_MODE=camera"
if /i "%NG_MODE%"=="hardware" set "NG_SERIAL_PORT=%~2"
if "%PORT%"=="" set "PORT=5000"
if "%NVIDIA_API_KEY%"=="" echo Note: NVIDIA_API_KEY is not set - Review session and Rank patients will show an error.
echo Starting NeuroGrip (%NG_MODE% mode) on http://localhost:%PORT%  -  login: therapist / therapist
if "%NG_NO_BROWSER%"=="" start "" cmd /c "timeout /t 5 >nul & start http://localhost:%PORT%"
".venv\Scripts\python" app.py
goto :eof
:fail
echo Setup failed. Install Python 3.10 (py -3.10) and try again.
pause
