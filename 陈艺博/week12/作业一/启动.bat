@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   楼道消防安全隐患识别 - 启动中...
echo.
set PY=E:\Anaconda\python.exe
if not exist "%PY%" set PY=python
"%PY%" run.py %*
echo.
pause
