@echo off
echo ============================================
echo  WholesaleOS - Installing Python packages
echo ============================================
echo.
echo This will take 5-10 minutes. Do NOT close this window.
echo.

cd /d "C:\Users\v-jmoten\wholesale-os"

echo [1/1] Installing all packages...
.\venv\Scripts\pip install -r requirements.txt --disable-pip-version-check

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo  SUCCESS - All packages installed!
    echo ============================================
    echo.
    echo Next step: run setup_db.py to create tables
    echo   .\venv\Scripts\python scripts\setup_db.py
    echo.
) else (
    echo.
    echo ERROR: Install failed. Check output above.
    echo.
)

pause
