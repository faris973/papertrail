@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Install Python 3.12 from python.org first. & pause & exit /b 1)
python bootstrap.py
if errorlevel 1 pause
