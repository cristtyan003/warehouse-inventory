@echo off
cd /d "%~dp0"

if not exist .venv (
    python -m venv .venv
    if errorlevel 1 goto :fail
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if errorlevel 1 goto :fail

if not defined DEMO_PASSWORD set DEMO_PASSWORD=demo-pass-123
if not defined SECRET_KEY set SECRET_KEY=local-dev-only-key

python seed.py
echo.
echo Server at http://127.0.0.1:5000
echo Demo logins: admin@example.com / editor@example.com / manager@example.com / viewer@example.com
echo Password: %DEMO_PASSWORD%
echo.
python app.py
pause
exit /b 0

:fail
echo Setup failed. Make sure Python 3.10+ is installed and on PATH.
pause
exit /b 1
