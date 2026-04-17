@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "CLIENT=%~1"
if "%CLIENT%"=="" set "CLIENT=Client_A"

set "PYTHON_EXE=.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto python_ok
set "PYTHON_EXE=..\.\.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto python_ok

REM No venv found — fall back to system Python
where py >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=py" & goto python_ok
where python >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=python" & goto python_ok

echo ERROR / Грешка: Python not found / Python не е намерен
echo Install Python 3.10+ from https://www.python.org/downloads/
echo Инсталирайте Python 3.10+ от https://www.python.org/downloads/
pause
exit /b 1

:python_ok

echo === Accounting-AI — intake run / Стартиране на входящия модул ===
"%PYTHON_EXE%" intake_v1.py --base-dir . --client "%CLIENT%"
if errorlevel 1 (
  echo ERROR during intake / Грешка по време на вход
  pause
  exit /b 1
)

echo === Invoice extraction / Извличане на фактури ===
"%PYTHON_EXE%" extract_invoices_v1.py --base-dir . --client "%CLIENT%"
if errorlevel 1 (
  echo ERROR during extraction / Грешка по време на извличане
  pause
  exit /b 1
)

echo === Delta Pro XML / Генериране на XML за Delta Pro ===
"%PYTHON_EXE%" generate_delta_xml.py --base-dir . --client "%CLIENT%"
if errorlevel 1 (
  echo ERROR during Delta XML generation / Грешка при генериране на Delta XML
  pause
  exit /b 1
)

echo Done / Готово: workflow completed for %CLIENT%
pause
