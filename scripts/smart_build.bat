@echo off
title WutheringWaves Navigator - Smart Build Tool

echo ================================================================
echo         WutheringWaves Navigator - Smart Build Tool v2.0
echo ================================================================
echo.
echo This tool can automatically locate your project directory!
echo.

:: Check Python
echo [CHECK] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.8+
    echo.
    pause
    exit /b 1
)

echo [OK] Python found
echo.

:: Check if smart_build.py exists in current directory
if exist "smart_build.py" (
    echo [OK] Smart build script found
    echo.
    echo [START] Running smart build...
    python smart_build.py
) else (
    echo [SEARCH] Smart build script not found in current directory
    echo [SEARCH] Trying to locate from project...
    
    :: Try to find the script in common locations
    if exist "..\smart_build.py" (
        echo [FOUND] Found script in parent directory
        python ..\smart_build.py
    ) else if exist "scripts\smart_build.py" (
        echo [FOUND] Found script in scripts directory
        python scripts\smart_build.py
    ) else if exist "..\scripts\smart_build.py" (
        echo [FOUND] Found script in parent\scripts directory
        python ..\scripts\smart_build.py
    ) else (
        echo [ERROR] Cannot find smart_build.py script!
        echo.
        echo Please make sure smart_build.py is in one of these locations:
        echo - Current directory
        echo - Parent directory
        echo - scripts\ subdirectory
        echo - ..\scripts\ directory
        echo.
        pause
        exit /b 1
    )
)

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
) else (
    echo.
    echo [SUCCESS] Build completed!
)

echo.
pause