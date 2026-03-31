@echo off
setlocal enabledelayedexpansion

title TeterAI CA — Windows Build

echo.
echo ============================================================
echo   TeterAI CA  ^|  Windows Installer Build
echo ============================================================
echo.

:: Check prerequisites
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 'uv' not found. Install from https://docs.astral.sh/uv/
    pause & exit /b 1
)

where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 'npm' not found. Install Node.js from https://nodejs.org/
    pause & exit /b 1
)

:: ------------------------------------------------------------
:: Install build dependencies (pyinstaller + Pillow)
:: ------------------------------------------------------------
echo Installing build dependencies...
uv sync --extra build
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install build dependencies.
    pause & exit /b 1
)
echo.

:: ------------------------------------------------------------
:: Step 1 — Icons
:: ------------------------------------------------------------
echo [1/4] Generating brand icons...
uv run scripts/generate_icon.py
if %errorlevel% neq 0 (
    echo [WARN] Icon generation failed — build will use default Electron icon.
)
echo.

:: ------------------------------------------------------------
:: Step 2 — Python backend (PyInstaller)
:: ------------------------------------------------------------
echo [2/4] Building Python backend bundle (this takes a few minutes)...
:: Remove any previous electron build so PyInstaller cannot accidentally bundle it
if exist "src\ui\desktop\dist-electron" (
    echo   Removing stale dist-electron from previous build...
    rmdir /s /q "src\ui\desktop\dist-electron"
)
uv run -- pyinstaller teterai-backend.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller build failed.
    pause & exit /b 1
)
echo.

:: ------------------------------------------------------------
:: Step 3 — React web frontend
:: ------------------------------------------------------------
echo [3/4] Building web frontend...
pushd src\ui\web
call npm install --silent
if %errorlevel% neq 0 (
    echo [ERROR] npm install failed in src/ui/web
    popd & pause & exit /b 1
)
call npm run build:desktop
if %errorlevel% neq 0 (
    echo [ERROR] Web frontend build failed.
    popd & pause & exit /b 1
)
popd
echo.

:: ------------------------------------------------------------
:: Step 4 — Electron installer
:: ------------------------------------------------------------
echo [4/4] Building Windows installer...
:: Kill any running TeterAI instance so app.asar is not file-locked
taskkill /f /im "TeterAI CA.exe" >nul 2>&1
taskkill /f /im "electron.exe" >nul 2>&1
taskkill /f /im "teterai-backend.exe" >nul 2>&1
timeout /t 2 /nobreak >nul
:: Delete the previous dist-electron output so no stale app.asar can be locked
if exist "src\ui\desktop\dist-electron" (
    echo   Removing previous dist-electron output...
    rmdir /s /q "src\ui\desktop\dist-electron"
)
:: Disable code signing — no cert for internal/MVP builds
set CSC_IDENTITY_AUTO_DISCOVERY=false
pushd src\ui\desktop
call npm install --silent
if %errorlevel% neq 0 (
    echo [ERROR] npm install failed in src/ui/desktop
    popd & pause & exit /b 1
)
:: Pre-extract winCodeSign cache to avoid symlink privilege errors.
:: electron-builder downloads this even when signing is disabled; the archive
:: contains macOS symlinks that fail to extract without Developer Mode or admin rights.
if not exist "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0\win\x64" (
    echo   Pre-extracting winCodeSign cache (skipping macOS symlinks^)...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/electron-userland/electron-builder-binaries/releases/download/winCodeSign-2.6.0/winCodeSign-2.6.0.7z' -OutFile ([System.IO.Path]::Combine($env:TEMP, 'winCodeSign-setup.7z')) -UseBasicParsing"
    if not errorlevel 1 (
        md "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0" 2>nul
        node_modules\7zip-bin\win\x64\7za.exe x "%TEMP%\winCodeSign-setup.7z" "-o%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0" -xr!darwin -xr!linux -y >nul
        del "%TEMP%\winCodeSign-setup.7z" 2>nul
        echo   winCodeSign cache ready.
    ) else (
        echo [WARN] winCodeSign pre-extract failed. Build may fail without Developer Mode.
    )
)
call npm run build
if %errorlevel% neq 0 (
    echo [ERROR] Electron builder failed.
    popd & pause & exit /b 1
)
popd

:: ------------------------------------------------------------
:: Done
:: ------------------------------------------------------------
echo.
echo ============================================================
echo   BUILD COMPLETE
echo ============================================================
echo.
echo   Installer:  src\ui\desktop\dist-electron\TeterAI CA Setup*.exe
echo.

:: Open the output folder in Explorer
explorer "src\ui\desktop\dist-electron"

pause
