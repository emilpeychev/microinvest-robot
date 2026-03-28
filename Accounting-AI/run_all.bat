@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto venv_ok
set "PYTHON_EXE=..\.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto venv_ok

echo ERROR / Грешка: Python venv not found / не е намерен
echo Checked / Проверени: .venv\Scripts\python.exe and ..\.venv\Scripts\python.exe
pause
exit /b 1

:venv_ok

echo === Accounting-AI — intake run / Стартиране на входящия модул ===
"%PYTHON_EXE%" intake_v1.py --base-dir . --client Client_A
if errorlevel 1 (
  echo ERROR during intake / Грешка по време на вход
  pause
  exit /b 1
)

echo === Invoice extraction / Извличане на фактури ===
"%PYTHON_EXE%" extract_invoices_v1.py --base-dir . --client Client_A
if errorlevel 1 (
  echo ERROR during extraction / Грешка по време на извличане
  pause
  exit /b 1
)

echo Done / Готово: workflow completed for Client_A
pause
