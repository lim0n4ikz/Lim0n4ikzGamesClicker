@echo off
setlocal
cd /d "%~dp0"

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller was not found. Install it with:
    echo python -m pip install pyinstaller
    exit /b 1
)

if not exist "lim0n4ikzgames.ico" (
    echo Missing lim0n4ikzgames.ico
    exit /b 1
)

if not exist "profiles.json" copy /y "profiles — копия1.json" "profiles.json" >nul
if not exist "settings.json" type nul > "settings.json"

rmdir /s /q build 2>nul
rmdir /s /q dist\Lim0n4ikzGamesClicker 2>nul

pyinstaller --noconfirm --clean --onedir --windowed --name "Lim0n4ikzGamesClicker" --icon "lim0n4ikzgames.ico" --add-data "profiles.json;." --add-data "settings.json;." --add-data "lim0n4ikzgames.ico;." main.py
if errorlevel 1 exit /b 1

set "ISCC="
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo Inno Setup 6 was not found. The application bundle was built successfully.
    echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo The PyInstaller build is ready in dist\Lim0n4ikzGamesClicker
    exit /b 1
)

"%ISCC%" "Lim0n4ikzGamesClicker.iss"
if errorlevel 1 exit /b 1

echo.
echo Installer created: installer\Lim0n4ikzGamesClickerSetup.exe
