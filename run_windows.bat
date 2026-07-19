@REM @echo off
@REM cd /d "%~dp0"
@REM if not exist ".venv" (
@REM     py -m venv .venv
@REM )
@REM call .venv\Scripts\activate
@REM python -m pip install -r requirements.txt
@REM start http://127.0.0.1:5000/admin
@REM python app.py
@REM pause


@echo off
cd /d "%~dp0"
title Portfolio Project Manager

echo Dang khoi dong Portfolio Project Manager...

where py >nul 2>nul
if %errorlevel%==0 (
    py -m pip install -r requirements.txt
    start "" http://127.0.0.1:5000/admin
    py app.py
    pause
    exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -m pip install -r requirements.txt
    start "" http://127.0.0.1:5000/admin
    python app.py
    pause
    exit /b
)

echo.
echo KHONG TIM THAY PYTHON.
echo Hay cai Python va chon "Add Python to PATH".
echo.
pause
