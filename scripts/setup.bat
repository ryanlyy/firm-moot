@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title AI Law Emulator - Setup

set PG_VERSION=16.9-1
set PG_DIR=C:\Program Files\PostgreSQL\16
set PG_BIN=%PG_DIR%\bin
set PG_INSTALLER=%TEMP%\pg-installer.exe
set PG_PORT=5432
set PG_SUPERPASS=postgres
set DB_USER=lawemu
set DB_PASS=changeme_in_production
set DB_NAME=lawemu
set APP_PORT=8000

:: Get script directory as project root
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..

echo.
echo ================================================================
echo   AI Law Emulator - Full Setup
echo   PostgreSQL + Python Deps + DB Init + Launch
echo ================================================================
echo.

:: ── 0. Check admin ──────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  * Requesting admin privileges ...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

:: ── 1. Check Python ─────────────────────────────────────
echo  [1/7] Checking Python ...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  !!! Python not found. Please install Python 3.10+ first.
    echo      https://www.python.org/downloads/
    goto :fail
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo         Python %%v found
echo.

:: ── 2. Install Python dependencies ──────────────────────
echo  [2/7] Installing Python dependencies ...
pip install -r "%PROJECT_DIR%\requirements.txt" --quiet
if %errorlevel% neq 0 (
    echo  !!! pip install failed
    goto :fail
)
echo         All Python packages installed
echo.

:: ── 3. Install PostgreSQL ───────────────────────────────
echo  [3/7] Checking PostgreSQL ...
if exist "%PG_BIN%\psql.exe" (
    echo         PostgreSQL already installed at %PG_DIR%
) else (
    if not exist "%PG_INSTALLER%" (
        echo         Downloading PostgreSQL %PG_VERSION% ...
        curl.exe -L -# -o "%PG_INSTALLER%" "https://get.enterprisedb.com/postgresql/postgresql-%PG_VERSION%-windows-x64.exe"
        if !errorlevel! neq 0 (
            echo  !!! Download failed
            goto :fail
        )
    ) else (
        echo         Installer cached at %PG_INSTALLER%
    )
    echo         Installing PostgreSQL (silent, may take a few minutes) ...
    "%PG_INSTALLER%" --mode unattended --unattendedmodeui none --superpassword %PG_SUPERPASS% --serverport %PG_PORT% --prefix "%PG_DIR%" --datadir "%PG_DIR%\data" --install_runtimes 0
    if !errorlevel! neq 0 (
        echo  !!! PostgreSQL installation failed
        goto :fail
    )
    echo         PostgreSQL installed
)
set PATH=%PG_BIN%;%PATH%
echo.

:: ── 4. Start PostgreSQL service ─────────────────────────
echo  [4/7] Starting PostgreSQL service ...
net start postgresql-x64-16 >nul 2>&1
:: service may already be running, that's fine

set READY=0
for /L %%i in (1,1,15) do (
    "%PG_BIN%\pg_isready" -p %PG_PORT% >nul 2>&1
    if !errorlevel! equ 0 (
        set READY=1
        goto :pg_ok
    )
    timeout /t 2 /nobreak >nul
)
:pg_ok
if %READY% equ 0 (
    echo  !!! PostgreSQL not ready on port %PG_PORT%
    goto :fail
)
echo         PostgreSQL running on port %PG_PORT%
echo.

:: ── 5. Create DB user ───────────────────────────────────
echo  [5/7] Creating database user '%DB_USER%' ...
set PGPASSWORD=%PG_SUPERPASS%
"%PG_BIN%\psql" -U postgres -p %PG_PORT% -tAc "SELECT 1 FROM pg_roles WHERE rolname='%DB_USER%'" 2>nul | findstr "1" >nul
if %errorlevel% equ 0 (
    echo         User '%DB_USER%' already exists
) else (
    "%PG_BIN%\psql" -U postgres -p %PG_PORT% -c "CREATE USER %DB_USER% WITH PASSWORD '%DB_PASS%' CREATEDB" >nul 2>&1
    if !errorlevel! neq 0 (
        echo  !!! Failed to create user
        goto :fail
    )
    echo         User '%DB_USER%' created
)
echo.

:: ── 6. Create database ──────────────────────────────────
echo  [6/7] Creating database '%DB_NAME%' ...
"%PG_BIN%\psql" -U postgres -p %PG_PORT% -tAc "SELECT 1 FROM pg_database WHERE datname='%DB_NAME%'" 2>nul | findstr "1" >nul
if %errorlevel% equ 0 (
    echo         Database '%DB_NAME%' already exists
) else (
    "%PG_BIN%\psql" -U postgres -p %PG_PORT% -c "CREATE DATABASE %DB_NAME% OWNER %DB_USER% ENCODING 'UTF8'" >nul 2>&1
    if !errorlevel! neq 0 (
        echo  !!! Failed to create database
        goto :fail
    )
    echo         Database '%DB_NAME%' created
)

:: Verify connection
set PGPASSWORD=%DB_PASS%
"%PG_BIN%\psql" -U %DB_USER% -d %DB_NAME% -p %PG_PORT% -tAc "SELECT 'ok'" 2>nul | findstr "ok" >nul
if %errorlevel% neq 0 (
    echo  !!! Connection test failed for user '%DB_USER%'
    goto :fail
)
echo         Connection verified
set PGPASSWORD=
echo.

:: ── 7. Create .env if missing ───────────────────────────
echo  [7/7] Checking .env config ...
if not exist "%PROJECT_DIR%\.env" (
    copy "%PROJECT_DIR%\.env.example" "%PROJECT_DIR%\.env" >nul
    echo         .env created from .env.example
) else (
    echo         .env already exists
)
echo.

:: ── Done ────────────────────────────────────────────────
echo ================================================================
echo   Setup complete!
echo.
echo   DATABASE_URL = postgresql://%DB_USER%:%DB_PASS%@localhost:%PG_PORT%/%DB_NAME%
echo.
echo   To start the app:
echo     cd %PROJECT_DIR%
echo     python run.py
echo.
echo   Then visit: http://127.0.0.1:%APP_PORT%
echo ================================================================
echo.

:: ── Kill stale servers on APP_PORT, then launch ─────────
echo  Starting app server ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%APP_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

cd /d "%PROJECT_DIR%"
start "AI Law Emulator" python run.py

timeout /t 4 /nobreak >nul
curl.exe -s -o nul -w "  HTTP status: %%{http_code}" http://127.0.0.1:%APP_PORT%/
echo.
echo.
echo  App running at http://127.0.0.1:%APP_PORT%
echo  Press any key to close this setup window (app keeps running).
echo.
pause >nul
exit /b 0

:fail
echo.
echo ================================================================
echo  !!! Setup failed. Check the errors above.
echo ================================================================
echo.
pause
exit /b 1
