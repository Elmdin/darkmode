@echo off
rem Umbra launcher. Double-click, or run from a terminal with arguments.
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

rem Find a Python. Each candidate is checked before it is overwritten, and the
rem executable is kept separate from its arguments so the path can be quoted --
rem it contains a space, and an unquoted path is split at it.
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PYARGS="
if not exist "%PYEXE%" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%PYEXE%" set "PYEXE=C:\Python314\python.exe"
if not exist "%PYEXE%" set "PYARGS=-3"
if not exist "%PYEXE%" set "PYEXE=py.exe"

if "%PYEXE%"=="py.exe" where py.exe >nul 2>&1 || goto :nopython

"%PYEXE%" %PYARGS% -X utf8 -m umbra %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" if "%~1"=="" pause
exit /b %RC%

:nopython
echo.
echo   No Python 3 found.
echo   Install 64-bit Python 3 from https://python.org and run this again.
echo   ^(The Windows Magnification API does not work under 32-bit Python.^)
echo.
pause
exit /b 9009
