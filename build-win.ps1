#Requires -Version 5.1
<#
.SYNOPSIS
    TeterAI CA — Windows installer build script.

.DESCRIPTION
    Runs the full 4-step build:
      1. Generate brand icons (build-resources/)
      2. Bundle Python backend with PyInstaller
      3. Build React web frontend (Vite)
      4. Package Windows NSIS installer with electron-builder

    Output: src/ui/desktop/dist-electron/TeterAI CA Setup <version>.exe
    The installer creates a desktop shortcut and Start Menu entry.

.EXAMPLE
    .\build-win.ps1
    .\build-win.ps1 -SkipIcons     # Skip icon generation
    .\build-win.ps1 -SkipBackend   # Skip PyInstaller (use existing dist/)
#>

param(
    [switch]$SkipIcons,
    [switch]$SkipBackend,
    [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

function Write-Step { param([int]$n, [int]$total, [string]$msg)
    Write-Host ""
    Write-Host "  [$n/$total] $msg" -ForegroundColor Cyan
    Write-Host "  " + ("-" * 56) -ForegroundColor DarkGray
}

function Require-Command { param([string]$cmd, [string]$hint)
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "  [ERROR] '$cmd' not found. $hint" -ForegroundColor Red
        exit 1
    }
}

# ---------------------------------------------------------------
# Banner
# ---------------------------------------------------------------
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor DarkGray
Write-Host "    TeterAI CA  |  Windows Installer Build" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor DarkGray
Write-Host ""

# ---------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------
Require-Command "uv"  "Install from https://docs.astral.sh/uv/"
Require-Command "npm" "Install Node.js from https://nodejs.org/"

Set-Location $ROOT

# ---------------------------------------------------------------
# Install build extras (pyinstaller + Pillow)
# ---------------------------------------------------------------
Write-Host "  Installing build dependencies..." -ForegroundColor Cyan
& uv sync --extra build
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] uv sync --extra build failed." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------
# Step 1 — Icons
# ---------------------------------------------------------------
if (-not $SkipIcons) {
    Write-Step 1 4 "Generating brand icons..."
    try {
        & uv run scripts/generate_icon.py
        if ($LASTEXITCODE -ne 0) { throw "icon generator returned $LASTEXITCODE" }
        Write-Host "  OK" -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] Icon generation failed: $_" -ForegroundColor Yellow
        Write-Host "  Build will continue with default Electron icon." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [1/4] Skipping icon generation (-SkipIcons)" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------
# Step 2 — Python backend
# ---------------------------------------------------------------
if (-not $SkipBackend) {
    Write-Step 2 4 "Building Python backend bundle (PyInstaller)..."
    Write-Host "  This may take several minutes on first run." -ForegroundColor DarkGray
    # Remove any previous electron build so PyInstaller cannot accidentally bundle it
    $staleDir = "$ROOT/src/ui/desktop/dist-electron"
    if (Test-Path $staleDir) {
        Write-Host "  Removing stale dist-electron from previous build..." -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $staleDir
    }
    & uv run -- pyinstaller teterai-backend.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] PyInstaller failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK  ->  dist/teterai-backend/" -ForegroundColor Green
} else {
    Write-Host "  [2/4] Skipping backend build (-SkipBackend)" -ForegroundColor DarkGray
    if (-not (Test-Path "dist/teterai-backend")) {
        Write-Host "  [ERROR] dist/teterai-backend not found. Run without -SkipBackend first." -ForegroundColor Red
        exit 1
    }
}

# ---------------------------------------------------------------
# Step 3 — React web frontend
# ---------------------------------------------------------------
if (-not $SkipWeb) {
    Write-Step 3 4 "Building React web frontend..."
    Set-Location "$ROOT/src/ui/web"
    & npm install --silent
    if ($LASTEXITCODE -ne 0) { Write-Host "  [ERROR] npm install failed" -ForegroundColor Red; exit 1 }
    & npm run build:desktop
    if ($LASTEXITCODE -ne 0) { Write-Host "  [ERROR] Vite build failed" -ForegroundColor Red; exit 1 }
    Set-Location $ROOT
    Write-Host "  OK  ->  src/ui/web/dist/" -ForegroundColor Green
} else {
    Write-Host "  [3/4] Skipping web build (-SkipWeb)" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------
# Step 4 — Electron / NSIS installer
# ---------------------------------------------------------------
Write-Step 4 4 "Packaging Windows NSIS installer (electron-builder)..."
# Kill any running TeterAI instance so app.asar is not file-locked
Write-Host "  Closing any running TeterAI CA instances..." -ForegroundColor DarkGray
Stop-Process -Name "TeterAI CA" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "teterai-backend" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
# Delete previous dist-electron so no stale app.asar can be locked by AV/Search
$distElectron = "$ROOT/src/ui/desktop/dist-electron"
if (Test-Path $distElectron) {
    Write-Host "  Removing previous dist-electron output..." -ForegroundColor DarkGray
    Remove-Item -Recurse -Force $distElectron
}
# Disable code signing — no cert for internal/MVP builds
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
Set-Location "$ROOT/src/ui/desktop"
& npm install --silent
if ($LASTEXITCODE -ne 0) { Write-Host "  [ERROR] npm install failed" -ForegroundColor Red; exit 1 }
# Pre-extract winCodeSign cache to avoid symlink privilege errors.
# electron-builder downloads this tool even when signing is disabled; the archive
# contains macOS symlinks that fail to extract without Developer Mode or admin rights.
$winCodeSignVersion = "winCodeSign-2.6.0"
$cacheDir = "$env:LOCALAPPDATA\electron-builder\Cache\winCodeSign\$winCodeSignVersion"
if (-not (Test-Path "$cacheDir\win\x64")) {
    Write-Host "  Pre-extracting winCodeSign cache (skipping macOS symlinks)..." -ForegroundColor Cyan
    $7za = "$ROOT\src\ui\desktop\node_modules\7zip-bin\win\x64\7za.exe"
    $archivePath = "$env:TEMP\winCodeSign-setup.7z"
    try {
        Invoke-WebRequest -Uri "https://github.com/electron-userland/electron-builder-binaries/releases/download/$winCodeSignVersion/$winCodeSignVersion.7z" -OutFile $archivePath -UseBasicParsing
        New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
        & $7za x $archivePath "-o$cacheDir" -xr!darwin -xr!linux -y | Out-Null
        Remove-Item $archivePath -Force -ErrorAction SilentlyContinue
        Write-Host "  winCodeSign cache ready." -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] winCodeSign pre-extract failed: $_" -ForegroundColor Yellow
        Write-Host "  Build may fail unless Windows Developer Mode is enabled." -ForegroundColor Yellow
    }
}
& npm run build
if ($LASTEXITCODE -ne 0) { Write-Host "  [ERROR] electron-builder failed" -ForegroundColor Red; exit 1 }
Set-Location $ROOT

# ---------------------------------------------------------------
# Done
# ---------------------------------------------------------------
$outDir   = "$ROOT/src/ui/desktop/dist-electron"
$installer = Get-ChildItem "$outDir" -Filter "*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor DarkGray
Write-Host "    BUILD COMPLETE" -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor DarkGray
Write-Host ""
if ($installer) {
    $sizeKB = [math]::Round($installer.Length / 1MB, 1)
    Write-Host "  Installer : $($installer.Name)" -ForegroundColor White
    Write-Host "  Size      : ${sizeKB} MB" -ForegroundColor White
    Write-Host "  Location  : $outDir" -ForegroundColor White
}
Write-Host ""
Write-Host "  The installer will:" -ForegroundColor DarkGray
Write-Host "    - Let users choose their install directory" -ForegroundColor DarkGray
Write-Host "    - Create a Desktop shortcut (TeterAI CA)" -ForegroundColor DarkGray
Write-Host "    - Add a Start Menu entry" -ForegroundColor DarkGray
Write-Host "    - Include an Uninstall entry in Add/Remove Programs" -ForegroundColor DarkGray
Write-Host ""

# Open output folder
Start-Process explorer.exe $outDir
