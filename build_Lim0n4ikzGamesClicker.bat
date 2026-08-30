@echo off
setlocal
cd /d "%~dp0"

echo === Cleaning previous PyInstaller build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo === Building Lim0n4ikzGamesClicker ===
pyinstaller --clean --noconfirm Lim0n4ikzGamesClicker.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    pause
    exit /b 1
)

echo.
echo BUILD OK: dist\Lim0n4ikzGamesClicker.exe
pause