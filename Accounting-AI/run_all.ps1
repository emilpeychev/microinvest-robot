param(
    [string]$BaseDir = $PSScriptRoot,
    [string]$Client  = "Client_A"
)

$ErrorActionPreference = "Stop"
$localPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$parentPython = Join-Path $PSScriptRoot "..\\.venv\Scripts\python.exe"

if (Test-Path $localPython) {
    $python = $localPython
} elseif (Test-Path $parentPython) {
    $python = $parentPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    Write-Error "Error / Грешка: Python not found. Install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
}

Write-Host "=== Accounting-AI intake run / Стартиране на входящия модул ==="
& $python (Join-Path $PSScriptRoot "intake_v1.py") --base-dir $BaseDir --client $Client

Write-Host "=== Invoice extraction / Извличане на фактури ==="
& $python (Join-Path $PSScriptRoot "extract_invoices_v1.py") --base-dir $BaseDir --client $Client

Write-Host "Done / Готово: workflow completed for $Client"
