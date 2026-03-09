@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Запуск бота RUN-RAY
echo ========================================
echo.
echo Установка зависимостей (если нужно)...
py -m pip install -r requirements.txt -q
echo.
py -u run.py
echo.
echo ========================================
pause
