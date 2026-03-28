# Accounting-AI — Installation & Usage Guide
# Наръчник за инсталация и употреба

---

## Table of Contents / Съдържание

1. [Requirements / Изисквания](#1-requirements--изисквания)
2. [Installation on Windows / Инсталация на Windows](#2-installation-on-windows--инсталация-на-windows)
3. [Installation on Linux or WSL / Инсталация на Linux или WSL](#3-installation-on-linux-or-wsl--инсталация-на-linux-или-wsl)
4. [Folder Structure / Структура на папките](#4-folder-structure--структура-на-папките)
5. [Configuration — Client Rules / Конфигурация — Правила за клиента](#5-configuration--client-rules--конфигурация--правила-за-клиента)
6. [Daily Workflow / Ежедневен работен процес](#6-daily-workflow--ежедневен-работен-процес)
7. [Running the Scripts / Стартиране на скриптовете](#7-running-the-scripts--стартиране-на-скриптовете)
8. [Understanding the Output / Разбиране на изхода](#8-understanding-the-output--разбиране-на-изхода)
9. [Automation — Task Scheduler (Windows) / Автоматизация](#9-automation--task-scheduler-windows--автоматизация)
10. [Scope Boundaries / Граници на системата](#10-scope-boundaries--граници-на-системата)
11. [Troubleshooting / Отстраняване на проблеми](#11-troubleshooting--отстраняване-на-проблеми)

---

## 1. Requirements / Изисквания

| Component / Компонент | Minimum / Минимум |
|---|---|
| Operating System / Операционна система | Windows 10/11 or Linux |
| Python | 3.10 or newer / 3.10 или по-нова |
| Disk space / Дисково пространство | 200 MB |
| Delta Pro | Installed separately / Инсталирана отделно |
| TRZ Pro | Installed separately (optional v1) / Инсталирана отделно (незадължително в v1) |

---

## 2. Installation on Windows / Инсталация на Windows

### Step 1 — Install Python / Стъпка 1 — Инсталирайте Python

1. Go to / Отидете на: https://www.python.org/downloads/
2. Download Python 3.10 or newer / Изтеглете Python 3.10 или по-нова версия
3. During install, check / По време на инсталацията, отметнете:
   - ✅ **Add Python to PATH**
   - ✅ **Install pip**
4. Verify / Проверете:
   ```powershell
   py --version
   ```
   Expected / Очаквано: `Python 3.10.x` or higher / или по-нова

### Step 2 — Copy the project / Стъпка 2 — Копирайте проекта

Copy the entire `Accounting-AI` folder to your PC.  
Копирайте цялата папка `Accounting-AI` на вашия компютър.

Recommended location / Препоръчано местоположение:
```
C:\Accounting-AI\
```

### Step 3 — Create virtual environment / Стъпка 3 — Създайте виртуална среда

Open PowerShell in the project folder / Отворете PowerShell в папката на проекта:
```powershell
cd C:\Accounting-AI
py -m venv .venv
```

### Step 4 — Install dependencies / Стъпка 4 — Инсталирайте зависимостите

```powershell
.\.venv\Scripts\python -m pip install openpyxl pymupdf pypdf
```

Verify / Проверете:
```powershell
.\.venv\Scripts\python -c "import openpyxl, pypdf; print('OK')"
```
Expected / Очаквано: `OK`

Optional PDF fallback on Linux/WSL / Допълнителен PDF fallback за Linux/WSL:
```bash
sudo apt install -y poppler-utils
```

### Step 5 — Create the PowerShell runner / Стъпка 5 — Създайте PowerShell стартер

Create a file `run_all.ps1` in `C:\Accounting-AI\` with content:  
Създайте файл `run_all.ps1` в `C:\Accounting-AI\` със съдържание:

```powershell
param(
    [string]$BaseDir = ".",
    [string]$Client  = "Client_A"
)
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python (Join-Path $PSScriptRoot "intake_v1.py")        --base-dir $BaseDir --client $Client
& $python (Join-Path $PSScriptRoot "extract_invoices_v1.py") --base-dir $BaseDir --client $Client
Write-Host "Done / Готово: workflow completed for $Client"
```

Run it / Стартирайте го:
```powershell
.\run_all.ps1 -BaseDir "." -Client "Client_A"
```

Or double-click via a `.bat` launcher / Или двоен клик чрез `.bat`:

Create `run_all.bat`:
```bat
@echo off
cd /d "%~dp0"
.venv\Scripts\python intake_v1.py --base-dir . --client Client_A
.venv\Scripts\python extract_invoices_v1.py --base-dir . --client Client_A
echo Done / Готово
pause
```

---

## 3. Installation on Linux or WSL / Инсталация на Linux или WSL

> Use this if you develop on Linux or run the workflow inside WSL while keeping files on a Windows drive (`/mnt/c/...`).
> Използвайте това, ако разработвате на Linux или изпълнявате потока в WSL, докато файловете са на Windows диск.

### Step 1 / Стъпка 1
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip poppler-utils
```

### Step 2 / Стъпка 2
```bash
cd /path/to/Accounting-AI
python3 -m venv .venv
.venv/bin/python -m pip install openpyxl pymupdf pypdf
```

### Step 3 / Стъпка 3
```bash
chmod +x run_all.sh
./run_all.sh . Client_A
```

> **WSL note / Бележка за WSL:** Keep all client files under `/mnt/c/Accounting-AI/` so Delta Pro on Windows can read the same Excel output files directly.
> Дръжте всички клиентски файлове в `/mnt/c/Accounting-AI/`, за да може Delta Pro на Windows директно да чете генерираните Excel файлове.

---

## 4. Folder Structure / Структура на папките

```
Accounting-AI/
│
├── Clients/
│   └── Client_A/
│       ├── 00_Incoming/      ← Drop raw files here / Пуснете суровите файлове тук
│       ├── 01_Processed/     ← Renamed & classified / Преименувани и класифицирани
│       ├── 02_Review/        ← Excel outputs for review / Excel изходи за проверка
│       ├── 03_Archive/       ← Finished files / Приключени файлове
│       └── 04_Unsupported/   ← Unsupported formats / Неподдържани формати
│
├── Rules/
│   └── client_rules.xlsx     ← Client config (VAT, accounts…) / Настройки на клиента
│
├── Templates/
│   ├── extracted_invoices.xlsx
│   ├── bank_match.xlsx
│   ├── proposed_entries.xlsx
│   └── client_email.txt
│
├── Logs/
│   └── run_log.txt           ← Audit trail / Дневник на действията
│
├── intake_v1.py              ← File intake script / Скрипт за вход
├── extract_invoices_v1.py    ← Invoice extraction / Извличане на фактури
├── run_all.sh                ← Linux one-command runner
├── run_all.ps1               ← Windows PowerShell runner (create per Step 2.5)
└── run_all.bat               ← Windows double-click runner (create per Step 2.5)
```

---

## 5. Configuration — Client Rules / Конфигурация — Правила за клиента

Open `Rules/client_rules.xlsx`.  
Отворете `Rules/client_rules.xlsx`.

Each sheet = one client / Всеки лист = един клиент.

| Field / Поле | Example / Пример | Notes / Бележки |
|---|---|---|
| Client Name | Client_A | Must match folder name / Трябва да съвпада с името на папката |
| Default VAT / ДДС по подразбиране | 20% | |
| Currency / Валута | BGN | |
| Known Suppliers / Известни доставчици | Lidl; Shell; Amazon | Semicolon-separated / Разделени с ; |
| Expense Keyword / Ключова дума разход | fuel | Matched in filename / Търси се в името |
| Expense Account / Сметка разход | 602 | Chart of accounts code / Код от сметкоплан |
| Revenue Keyword / Ключова дума приход | sales | |
| Revenue Account / Сметка приход | 701 | |
| Bank Name / Банка | UniCredit | |
| Reviewer / Проверяващ | WifeName | |

To add a second client / За да добавите втори клиент:
1. Add a new sheet named `Client_B` / Добавете нов лист с име `Client_B`
2. Create folder `Clients/Client_B/` with the 4 subfolders / Създайте папка `Clients/Client_B/` с 4-те подпапки
3. Fill in the same fields / Попълнете същите полета

---

## 6. Daily Workflow / Ежедневен работен процес

```
Staff / Персонал
      │
      ▼
Drop files into 00_Incoming        ← PDFs, JPGs, bank CSV/XLSX
Пуснете файлове в 00_Incoming
      │
      ▼
Run workflow (once per day)
Стартирайте потока (веднъж дневно)
      │
      ▼
System generates in 02_Review:     ← extracted_invoices.xlsx
Системата генерира в 02_Review:       bank_match.xlsx (coming next / предстои)
                                       proposed_entries.xlsx (coming next)
      │
      ▼
Your wife opens 02_Review
Съпругата Ви отваря 02_Review
      │
      ▼
Reviews & corrects Excel files
Проверява и коригира Excel файловете
      │
      ▼
Imports reviewed entries into Delta Pro (manual / ръчно)
Импортира проверените записи в Delta Pro
```

---

## 7. Running the Scripts / Стартиране на скриптовете

### Windows / Windows

One-command / Едно команда:
```powershell
cd C:\Accounting-AI
.\run_all.bat
```

Or individual steps / Или по стъпки:
```powershell
.\.venv\Scripts\python intake_v1.py --base-dir . --client Client_A
.\.venv\Scripts\python extract_invoices_v1.py --base-dir . --client Client_A
```

Dry run (no files moved) / Тестов режим (без преместване):
```powershell
.\.venv\Scripts\python intake_v1.py --base-dir . --client Client_A --dry-run
```

### Linux / WSL

```bash
cd /path/to/Accounting-AI
./run_all.sh . Client_A
```

### Script options / Опции на скрипта

#### `intake_v1.py`

| Option / Опция | Default / По подразбиране | Description / Описание |
|---|---|---|
| `--base-dir` | `.` | Path to Accounting-AI root / Път до корена |
| `--client` | `Client_A` | Client folder name / Клиентска папка |
| `--dry-run` | off | Preview without moving files / Преглед без преместване |

#### `extract_invoices_v1.py`

| Option / Опция | Default / По подразбиране | Description / Описание |
|---|---|---|
| `--base-dir` | `.` | Path to Accounting-AI root / Път до корена |
| `--client` | `Client_A` | Client folder name / Клиентска папка |

---

## 8. Understanding the Output / Разбиране на изхода

### `02_Review/extracted_invoices.xlsx`

| Column / Колона | Filled by AI / Попълва AI | Notes / Бележки |
|---|---|---|
| Client | ✅ | From filename / От името на файла |
| File Name | ✅ | Original file / Оригинален файл |
| Document Type | ✅ | Invoice / Receipt / Bank / Other |
| Supplier/Customer | ✅ | From filename, verify! / Проверете! |
| Invoice Number | ❌ | Fill manually / Попълнете ръчно |
| Invoice Date | ✅ | From filename / От името |
| Net Amount | ❌ | Fill manually / Попълнете ръчно |
| VAT Amount | ❌ | Fill manually / Попълнете ръчно |
| Gross Amount | ✅ | From filename / От името |
| Currency | ✅ | BGN by default / BGN по подразбиране |
| Confidence Score | ✅ | 0.0–1.0, flag <0.5 / маркирайте <0.5 |
| Notes | ✅ | AI warnings / Предупреждения |

### `Logs/run_log.txt`

Each run appends lines like / Всяко изпълнение добавя редове като:
```
2026-03-28 09:13 Classified / Класифициран invoice_Lidl.pdf като invoice (reason/причина=name)
2026-03-28 09:13 Renamed / Преименуван invoice_Lidl.pdf -> Client_A_2025-03-18_Invoice_Lidl_124.50.pdf
2026-03-28 09:13 Moved / Преместен в 01_Processed
2026-03-28 09:13 Extracted invoice row / Извлечен ред от Client_A_2025-03-18_Invoice_Lidl_124.50.pdf
```

### File naming format / Формат на именуване
```
CLIENT_YYYY-MM-DD_TYPE_COUNTERPARTY_AMOUNT.ext
```
Example / Пример:
```
Client_A_2025-03-18_Invoice_Lidl_124.50.pdf
```
If data is missing / Ако липсват данни → `UNKNOWNDATE`, `Unknown`

---

## 9. Automation — Task Scheduler (Windows) / Автоматизация

To run automatically every morning / За автоматично изпълнение всяка сутрин:

1. Open Task Scheduler / Отворете Планировчик на задачи → `taskschd.msc`
2. Click **Create Basic Task** / Кликнете **Създай основна задача**
3. Set trigger / Задайте тригер: **Daily at 08:00** / Ежедневно в 08:00
4. Set action / Задайте действие: **Start a program / Стартирай програма**
   - Program / Програма: `C:\Accounting-AI\.venv\Scripts\python.exe`
   - Arguments / Аргументи: `intake_v1.py --base-dir . --client Client_A`
   - Start in / Стартирай в: `C:\Accounting-AI`
5. Repeat for `extract_invoices_v1.py` / Повторете за `extract_invoices_v1.py`
6. Save / Запишете

Alternatively use the `.bat` file as the program / Алтернативно използвайте `.bat` файла като програмата.

---

## 10. Scope Boundaries / Граници на системата

### The AI is allowed to / Системата може да:
- ✅ Sort files / Сортира файлове
- ✅ Rename files / Преименува файлове
- ✅ Move files / Премества файлове
- ✅ Extract data to Excel / Извлича данни към Excel
- ✅ Suggest matches / Предлага съвпадения
- ✅ Log all actions / Записва всички действия

### The AI is NOT allowed to / Системата НЕ може да:
- ❌ Post directly to Delta Pro / Контира директно в Delta Pro
- ❌ Overwrite final books / Презаписва окончателни счетоводни данни
- ❌ File tax declarations / Подава данъчни декларации
- ❌ Run payroll / Изчислява заплати (TRZ)
- ❌ Modify schedules / Промяна на графици

> ⚠️ Human review in `02_Review` is **mandatory** before any Delta Pro import.
> ⚠️ Ръчната проверка в `02_Review` е **задължителна** преди всеки импорт в Delta Pro.

---

## 11. Troubleshooting / Отстраняване на проблеми

### `ModuleNotFoundError: No module named 'openpyxl'`
You are using the wrong Python. Always use the `.venv` Python.  
Използвате грешен Python. Винаги използвайте Python от `.venv`.
```powershell
# Windows
.\.venv\Scripts\python -m pip install openpyxl
# Linux
.venv/bin/python -m pip install openpyxl
```

### `FileNotFoundError: Missing required path(s)`
The folder structure is incomplete. Re-create it:  
Структурата на папките е непълна. Пресъздайте я:
```powershell
# Windows PowerShell
mkdir Clients\Client_A\00_Incoming, Clients\Client_A\01_Processed, Clients\Client_A\02_Review, Clients\Client_A\03_Archive, Clients\Client_A\04_Unsupported, Rules, Templates, Logs
```

### File in `02_Review` instead of `01_Processed`
The filename was not recognized. Rename the file to include a keyword:  
Името на файла не бе разпознато. Преименувайте го да съдържа ключова дума:
- For invoices / За фактури: include `invoice` or `inv` or `faktura`
- For receipts / За касови бонове: include `receipt` or `bon`
- For bank files / За банкови: include `bank` or `statement`, or use `.csv`/`.xlsx`

### Confidence Score below 0.5 / Оценка на доверие под 0.5
The AI was unsure. Check the `Notes` column and fill in missing fields manually.  
Системата не е сигурна. Проверете колона `Notes` и попълнете липсващите полета ръчно.

### Logs show `UNKNOWNDATE`
The date was not found in the filename. Best practice:  
Датата не бе открита в името. Добра практика:
```
invoice_Lidl_2025-03-18_124.50.pdf    ← GOOD / ДОБРО
invoice_Lidl.pdf                       ← date missing / липсва дата
```

---

*Version / Версия: 1.0 — March 2026*  
*Microinvest Delta Pro + TRZ Pro compatible / Съвместимо с*
