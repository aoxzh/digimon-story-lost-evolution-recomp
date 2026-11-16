@echo off
setlocal
set "TITLE_DIR=%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%TITLE_DIR%\tools\lostevo.py" play %*
  exit /b %errorlevel%
)
where python >nul 2>nul
if %errorlevel%==0 (
  python "%TITLE_DIR%\tools\lostevo.py" play %*
  exit /b %errorlevel%
)
echo Python 3 not found. Install Python 3.10+ or run: py -3 tools\lostevo.py play
exit /b 1
