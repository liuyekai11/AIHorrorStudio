@echo off
chcp 65001 >nul
rem AI Horror Studio V2.0 test runner
rem 1) unit tests  2) GUI smoke test (create project, import, edit, story, AI media, batch, render)
rem Keep this file pure ASCII: non-ASCII text breaks cmd.exe parsing on zh-CN Windows.

setlocal EnableExtensions
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

set "FFMPEG_BIN=%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
if not exist "%FFMPEG_BIN%" (
    where ffmpeg >nul 2>nul && for /f "delims=" %%i in ('where ffmpeg') do set "FFMPEG_BIN=%%i"
)

set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo === Unit tests ===
"%PY%" -m unittest discover -s tests -v
if errorlevel 1 goto :fail

echo.
echo === GUI smoke test ===
"%PY%" "tests\gui_smoke.py"
if errorlevel 1 goto :fail

echo.
echo ALL TESTS PASSED.
pause
exit /b 0

:fail
echo.
echo TEST FAILED. See output above.
pause
exit /b 1
