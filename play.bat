@echo off
setlocal
rem Digimon Story: Lost Evolution Recomp - first-run setup and launcher.
rem Drag ROM files onto this file, or put them in the roms folder.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
title Digimon Story: Lost Evolution Recomp

set "PY="
set "PYARG="
if exist "%ROOT%\kit\python\python.exe" set "PY=%ROOT%\kit\python\python.exe"
if not defined PY (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && (set "PY=py" & set "PYARG=-3")
)
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo No Python 3.10+ found; fetching a private copy into kit\python ...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\bootstrap_python.ps1"
  if errorlevel 1 goto nopython
  if not exist "%ROOT%\kit\python\python.exe" goto nopython
  set "PY=%ROOT%\kit\python\python.exe"
)

"%PY%" %PYARG% "%ROOT%\tools\setup_kit.py" %*
if errorlevel 1 goto failed
exit /b 0

:nopython
echo.
echo Could not get Python. Install Python 3.10+ from python.org and run play.bat again.
pause
exit /b 1

:failed
echo.
echo Something went wrong. Details are above and in run\build.log.
pause
exit /b 1
