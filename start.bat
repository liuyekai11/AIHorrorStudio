@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem AI Horror Studio V2.0 launcher
rem NOTE: keep this file pure ASCII; non-ASCII text breaks cmd.exe parsing

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

set "PY="

rem 1) project venv
if exist "%APP_DIR%.venv\Scripts\python.exe" set "PY=%APP_DIR%.venv\Scripts\python.exe"

rem 2) official CPython 3.11 install
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

rem 3) bundled runtime used for development
if not defined PY if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not defined PY (
    echo [ERROR] Python not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/ and retry.
    pause
    exit /b 1
)

rem Launch detached; startup errors are logged to error.log by main.py
start "" "%PY%" "%APP_DIR%main.py"
exit /b 0
