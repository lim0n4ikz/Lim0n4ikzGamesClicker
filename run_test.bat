@echo off
setlocal
cd /d "%~dp0"

if not defined LOCALAPPDATA (
    echo LOCALAPPDATA is not defined. Cannot create an isolated test profile.
    pause
    exit /b 1
)

if not exist "%~dp0main.py" (
    echo main.py was not found next to run_test.bat.
    pause
    exit /b 1
)

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Project Python environment was not found:
    echo %PYTHON%
    echo Create it and install requirements.txt before running this launcher.
    pause
    exit /b 1
)

set "LIM0N4KZ_CLICKER_DATA_DIR=%LOCALAPPDATA%\Lim0n4ikzGamesClicker-Test"
echo Running test copy. Test settings and profiles are stored in:
echo %LIM0N4KZ_CLICKER_DATA_DIR%
"%PYTHON%" "%~dp0main.py"
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%
