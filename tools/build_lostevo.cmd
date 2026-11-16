@echo off
setlocal
set "TITLE_DIR=%~dp0.."
if "%~1"=="" goto build
if /i "%~1"=="all" goto build
if /i "%~1"=="build" goto build
if /i "%~1"=="smoke" goto verify
if /i "%~1"=="verify" goto verify
goto passthrough
:build
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%TITLE_DIR%\tools\lostevo.py" build %2 %3 %4 %5
  exit /b %errorlevel%
)
python "%TITLE_DIR%\tools\lostevo.py" build %2 %3 %4 %5
exit /b %errorlevel%
:verify
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%TITLE_DIR%\tools\lostevo.py" verify %2 %3 %4 %5
  exit /b %errorlevel%
)
python "%TITLE_DIR%\tools\lostevo.py" verify %2 %3 %4 %5
exit /b %errorlevel%
:passthrough
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%TITLE_DIR%\tools\lostevo.py" %*
  exit /b %errorlevel%
)
python "%TITLE_DIR%\tools\lostevo.py" %*
exit /b %errorlevel%
