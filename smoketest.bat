@echo off
rem Unattended smoke test for umbra. Every step restores the screen.
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PYARGS="
if not exist "%PYEXE%" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%PYEXE%" set "PYEXE=C:\Python314\python.exe"
if not exist "%PYEXE%" set "PYARGS=-3"
if not exist "%PYEXE%" set "PYEXE=py.exe"

rem The quotes are part of RUN's value, so the path survives having a space in it.
set RUN="%PYEXE%" %PYARGS% -X utf8 -m umbra

echo   python:  %PYEXE% %PYARGS%
echo   folder:  %CD%
%RUN% --version
if errorlevel 1 goto :broken

echo.
echo ============================================================
echo  1/5  doctor  -- environment check, no visual effect
echo ============================================================
%RUN% doctor
echo   [exit %errorlevel%]

echo.
echo ============================================================
echo  2/5  preview -- colour maths, no visual effect
echo ============================================================
%RUN% preview dark
echo   [exit %errorlevel%]

echo.
echo ============================================================
echo  3/5  region  -- 600x400 overlay, top-left, 8 seconds
echo        The window it covers should go dark. Nothing else.
echo ============================================================
%RUN% --region 40,40,600,400 --duration 8 --no-save
echo   [exit %errorlevel%]

echo.
echo ============================================================
echo  4/5  fullscreen -- whole desktop, 6 seconds
echo ============================================================
%RUN% --fullscreen --duration 6 --no-save
echo   [exit %errorlevel%]

echo.
echo ============================================================
echo  5/5  reset -- make certain nothing was left applied
echo ============================================================
%RUN% reset
echo   [exit %errorlevel%]

echo.
echo Smoke test finished. If your screen still looks wrong, run:  umbra.bat reset
pause
exit /b 0

:broken
echo.
echo   Could not start Python at: %PYEXE%
echo   Run this to see what is installed:   py.exe -0p
echo.
pause
exit /b 9009
