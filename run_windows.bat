@echo off
setlocal
cd /d "%~dp0"

set "LOG_FILE=%~dp0windows-run.log"
echo ==== Golden setup and run: %DATE% %TIME% ==== > "%LOG_FILE%"
echo Checking for Python...
py -3 --version >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto missing_python

if not exist ".venv\Scripts\python.exe" (
    echo Preparing Golden for first use...
    py -3 -m venv ".venv" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto setup_failed
)

echo Installing or checking required components...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto setup_failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "requirements.txt" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto setup_failed

echo.
echo Golden is starting. Keep this window open.
echo When it starts, open http://127.0.0.1:8000 in your browser.
echo Log file: "%LOG_FILE%"
echo ==== Golden application output ==== >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m processor >> "%LOG_FILE%" 2>&1
echo.
echo Golden has stopped. See the log file for details:
echo "%LOG_FILE%"
goto finish

:missing_python
echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/windows/
echo During installation, check "Add python.exe to PATH" and keep the Python Launcher enabled.
echo Python check failed. See "%LOG_FILE%" for details. >> "%LOG_FILE%"
goto finish

:setup_failed
echo Setup did not finish. Check your internet connection, then see:
echo "%LOG_FILE%"
echo Setup failed. See the messages above. >> "%LOG_FILE%"

:finish
echo.
pause
endlocal
