# Accounting-AI — Windows Installation & Usage Guide
# Инсталация и употреба на Windows

---

## What does this program do? / Какво прави тази програма?

The system automatically:
1. Takes files from `00_Incoming` folder (invoices, receipts, bank statements)
2. Recognizes them by name and file extension
3. Renames them to a standard format and moves them to `01_Processed`
4. Generates an Excel spreadsheet `extracted_invoices.xlsx` in `02_Review` with extracted data
5. You review the spreadsheet and manually import it into Delta Pro

**There is no graphical interface.** You work with folders and double-click a `.bat` file.

---

## Step 1 — Install Python / Инсталирайте Python

1. Go to: https://www.python.org/downloads/
2. Download Python **3.10 or newer**
3. **IMPORTANT** — during installation, check these boxes:
   - ✅ **Add Python to PATH**
   - ✅ **Install pip**
4. Verify — open PowerShell (press `Win+X` → **Windows PowerShell**) and type:
   ```
   py --version
   ```
   You should see something like: `Python 3.12.x`

---

## Step 2 — Get the project / Вземете проекта

### Option A — Git clone (recommended)

If you have Git installed (download from https://git-scm.com/download/win if not):
```
cd C:\
git clone https://github.com/YOUR_USERNAME/microinvest-robot.git
cd microinvest-robot\Accounting-AI
```

### Option B — Manual copy

Copy the entire `Accounting-AI` folder to your PC.

Recommended location:
```
C:\Accounting-AI\
```

The structure should look like this:
```
C:\Accounting-AI\
├── intake_v1.py
├── extract_invoices_v1.py
├── run_all.bat
├── run_all.ps1
├── Templates\
│   └── extracted_invoices.xlsx
├── Rules\
│   └── client_rules.xlsx
└── ...
```

---

## Step 3 — Create virtual environment / Създайте виртуална среда

Open PowerShell and type:
```
cd C:\Accounting-AI
py -m venv .venv
```

This creates a `.venv` folder — an isolated Python environment for the project.

---

## Step 4 — Install dependencies / Инсталирайте зависимостите

In the same PowerShell window:
```
.\.venv\Scripts\python -m pip install openpyxl pymupdf pypdf
```

Verify:
```
.\.venv\Scripts\python -c "import openpyxl, pypdf; print('OK')"
```
If you see `OK` — everything is fine.

---

## Step 5 — Create client folders / Създайте клиентски папки

In PowerShell:
```powershell
cd C:\Accounting-AI
$base = "Clients\Client_A"
foreach ($dir in @("00_Incoming","01_Processed","02_Review","03_Archive","04_Unsupported")) {
    New-Item -ItemType Directory -Force -Path "$base\$dir"
}
New-Item -ItemType Directory -Force -Path Rules, Templates, Logs
```

**Or if you prefer cmd.exe** (press `Win+R` → type `cmd` → Enter):
```
cd /d C:\Accounting-AI
mkdir Clients\Client_A\00_Incoming
mkdir Clients\Client_A\01_Processed
mkdir Clients\Client_A\02_Review
mkdir Clients\Client_A\03_Archive
mkdir Clients\Client_A\04_Unsupported
mkdir Rules
mkdir Templates
mkdir Logs
```

> ⚠️ The `Templates\` folder must contain the file `extracted_invoices.xlsx` — it comes with the project.

---

## Step 6 — Run the program / Пуснете програмата

### Option A — Double-click (easiest)

1. Open the `C:\Accounting-AI\` folder in Explorer
2. Double-click **`run_all.bat`**
3. A black window will open, process the files, and say `Done / Готово`

By default it processes `Client_A`.

### Option B — PowerShell

```
cd C:\Accounting-AI
.\run_all.ps1 -Client "Client_A"
```

For a different client:
```
.\run_all.ps1 -Client "Client_B"
```

### Option C — cmd.exe

```
cd /d C:\Accounting-AI
run_all.bat Client_A
```

---

## Daily Workflow / Ежедневен работен процес

```
    YOU
     │
     ▼
  Drop files into: Clients\Client_A\00_Incoming\
  (PDF invoices, JPG receipts, CSV/XLSX bank statements)
     │
     ▼
  Double-click run_all.bat
     │
     ▼
  The program:
  • Renames and moves files to 01_Processed\
  • Creates Excel spreadsheet in 02_Review\extracted_invoices.xlsx
     │
     ▼
  Open 02_Review\extracted_invoices.xlsx in Excel
     │
     ▼
  Review and correct the data
  (supplier, date, amount, invoice number)
     │
     ▼
  Manually import into Delta Pro
```

---

## Output columns / Какво съдържа Excel таблицата

| Column | Auto-filled | Notes |
|---|---|---|
| Client | ✅ | From filename |
| File Name | ✅ | Original name |
| Document Type | ✅ | Invoice / Receipt / Bank / Other |
| Supplier/Customer | ✅ | From filename — **verify!** |
| Invoice Number | ❌ | Fill manually |
| Invoice Date | ✅ | From filename |
| Net Amount | ❌ | Fill manually |
| VAT Amount | ❌ | Fill manually |
| Gross Amount | ✅ | From filename |
| Currency | ✅ | BGN by default |
| Confidence Score | ✅ | 0.0–1.0 — if below 0.5, check carefully |
| Mandatory Review | ✅ | `Yes` = from image, must verify |
| Notes | ✅ | System warnings |

---

## File naming tips / Именуване на файлове

For better recognition, name your files like this:

```
faktura_Lidl_2026-03-18_124.50.pdf      ← GOOD ✅
invoice_Shell_2026-03-20_89.99.pdf      ← GOOD ✅
kasov_bon_Kaufland_2026-03-15_42.00.jpg  ← GOOD ✅
scan001.pdf                              ← BAD ❌ (no data)
```

Keywords the system recognizes:
- **Invoices:** `invoice`, `inv`, `factura`, `faktura`, `fakt`, `bill`
- **Receipts:** `receipt`, `kasov`, `bon`, `slip`
- **Bank statements:** `bank`, `statement`, `extract`, `banka`

---

## Automation / Автоматизация (optional)

To run automatically every morning:

1. Press `Win+R` → type `taskschd.msc` → Enter
2. Click **Create Basic Task**
3. Trigger: **Daily at 08:00**
4. Action: **Start a program**
   - Program: `C:\Accounting-AI\run_all.bat`
   - Start in: `C:\Accounting-AI`
5. Save

---

## Troubleshooting / Отстраняване на проблеми

### Error: `ModuleNotFoundError: No module named 'openpyxl'`

You are using the wrong Python. Reinstall:
```
cd C:\Accounting-AI
.\.venv\Scripts\python -m pip install openpyxl pymupdf pypdf
```

### Error: `FileNotFoundError: Missing required path(s)`

Folders were not created. Go back to **Step 5** and run the commands.

### File went to `02_Review` instead of `01_Processed`

The filename was not recognized. Rename it to include a keyword:
- `invoice`, `faktura`, `receipt`, `bon`, `bank`

### Confidence Score is below 0.5

The system is not sure. Check the `Notes` column and fill in missing fields manually.

### Logs — where to see what the program did

Open `Logs\run_log.txt` with Notepad. Each line shows what was classified, renamed, and moved.

---

## Limitations / Какво НЕ прави тази програма

- ❌ Does **NOT** post directly to Delta Pro
- ❌ Does **NOT** overwrite accounting data
- ❌ Does **NOT** file tax declarations
- ❌ Does **NOT** calculate payroll (TRZ)
- ❌ Does **NOT** have a graphical interface — works with files and Excel

> ⚠️ Manual review in `02_Review` is **mandatory** before any Delta Pro import.

---

*Version: 1.1.2 — March 2026*
*Compatible with Microinvest Delta Pro + TRZ Pro*
