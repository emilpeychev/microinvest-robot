# Accounting-AI — Инсталация и употреба на Windows
# Windows Installation & Usage Guide

---

## Какво прави тази програма? / What does this program do?

Системата автоматично:
1. Взема файловете от папка `00_Incoming` (фактури, касови бонове, банкови извлечения)
2. Разпознава ги по име и разширение
3. Преименува ги по стандарт и ги премества в `01_Processed`
4. Генерира Excel таблица `extracted_invoices.xlsx` в `02_Review` с извлечените данни
5. Вие проверявате таблицата и я импортирате ръчно в Delta Pro

**Няма графичен интерфейс.** Работи се с папки и двоен клик на `.bat` файл.

---

## Стъпка 1 — Инсталирайте Python / Install Python

1. Отворете: https://www.python.org/downloads/
2. Изтеглете Python **3.10 или по-нова** версия
3. **ВАЖНО** — по време на инсталацията отметнете:
   - ✅ **Add Python to PATH**
   - ✅ **Install pip**
4. Проверка — отворете PowerShell (натиснете `Win+X` → **Windows PowerShell**) и напишете:
   ```
   py --version
   ```
   Трябва да видите нещо като: `Python 3.12.x`

---

## Стъпка 2 — Копирайте проекта / Copy the project

Копирайте цялата папка `Accounting-AI` на вашия компютър.

Препоръчано местоположение:
```
C:\Accounting-AI\
```

Структурата трябва да изглежда така:
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

## Стъпка 3 — Създайте виртуална среда / Create virtual environment

Отворете PowerShell и напишете:
```
cd C:\Accounting-AI
py -m venv .venv
```

Ще се създаде папка `.venv` — това е изолирана Python среда за проекта.

---

## Стъпка 4 — Инсталирайте зависимостите / Install dependencies

В същия PowerShell прозорец:
```
.\.venv\Scripts\python -m pip install openpyxl pymupdf pypdf
```

Проверка:
```
.\.venv\Scripts\python -c "import openpyxl, pypdf; print('OK')"
```
Ако видите `OK` — всичко е наред.

---

## Стъпка 5 — Създайте клиентски папки / Create client folders

В PowerShell:
```powershell
cd C:\Accounting-AI
$base = "Clients\Client_A"
foreach ($dir in @("00_Incoming","01_Processed","02_Review","03_Archive","04_Unsupported")) {
    New-Item -ItemType Directory -Force -Path "$base\$dir"
}
New-Item -ItemType Directory -Force -Path Rules, Templates, Logs
```

**Или ако предпочитате cmd.exe** (натиснете `Win+R` → напишете `cmd` → Enter):
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

> ⚠️ Папка `Templates\` трябва да съдържа файла `extracted_invoices.xlsx` — той идва с проекта.

---

## Стъпка 6 — Пуснете програмата / Run the program

### Вариант А — Двоен клик (най-лесно)

1. Отворете папката `C:\Accounting-AI\` в Explorer
2. Кликнете двойно на **`run_all.bat`**
3. Ще се отвори черен прозорец, ще обработи файловете и ще каже `Done / Готово`

По подразбиране обработва `Client_A`.

### Вариант Б — PowerShell

```
cd C:\Accounting-AI
.\run_all.ps1 -Client "Client_A"
```

За друг клиент:
```
.\run_all.ps1 -Client "Client_B"
```

### Вариант В — cmd.exe

```
cd /d C:\Accounting-AI
run_all.bat Client_A
```

---

## Ежедневен работен процес / Daily Workflow

```
    ВИЕ
     │
     ▼
  Пускате файлове в: Clients\Client_A\00_Incoming\
  (PDF фактури, JPG касови бонове, CSV/XLSX банкови извлечения)
     │
     ▼
  Кликвате двойно на run_all.bat
     │
     ▼
  Програмата:
  • Преименува и премества файловете в 01_Processed\
  • Създава Excel таблица в 02_Review\extracted_invoices.xlsx
     │
     ▼
  Отваряте 02_Review\extracted_invoices.xlsx в Excel
     │
     ▼
  Проверявате и коригирате данните
  (доставчик, дата, сума, номер на фактура)
     │
     ▼
  Импортирате ръчно в Delta Pro
```

---

## Какво съдържа Excel таблицата / Output columns

| Колона | Попълва се автоматично | Бележки |
|---|---|---|
| Client | ✅ | От името на файла |
| File Name | ✅ | Оригинално име |
| Document Type | ✅ | Invoice / Receipt / Bank / Other |
| Supplier/Customer | ✅ | От името на файла — **проверете!** |
| Invoice Number | ❌ | Попълнете ръчно |
| Invoice Date | ✅ | От името на файла |
| Net Amount | ❌ | Попълнете ръчно |
| VAT Amount | ❌ | Попълнете ръчно |
| Gross Amount | ✅ | От името на файла |
| Currency | ✅ | BGN по подразбиране |
| Confidence Score | ✅ | 0.0–1.0 — ако е под 0.5, проверете внимателно |
| Mandatory Review | ✅ | `Yes` = от снимка, задължителна проверка |
| Notes | ✅ | Предупреждения от системата |

---

## Именуване на файлове / File naming tips

За по-добро разпознаване, именувайте файловете така:

```
faktura_Lidl_2026-03-18_124.50.pdf      ← ДОБРО ✅
фактура_Shell_2026-03-20_89.99.pdf      ← ДОБРО ✅
kasov_bon_Kaufland_2026-03-15_42.00.jpg  ← ДОБРО ✅
scan001.pdf                              ← ЛОШО ❌ (няма данни)
```

Ключови думи, които системата разпознава:
- **Фактури:** `invoice`, `inv`, `factura`, `faktura`, `fakt`, `bill`
- **Касови бонове:** `receipt`, `kasov`, `bon`, `slip`
- **Банкови:** `bank`, `statement`, `extract`, `banka`

---

## Автоматизация / Automation (по желание)

За да се стартира автоматично всяка сутрин:

1. Натиснете `Win+R` → напишете `taskschd.msc` → Enter
2. Кликнете **Създай основна задача** / **Create Basic Task**
3. Тригер: **Ежедневно в 08:00**
4. Действие: **Стартирай програма**
   - Програма: `C:\Accounting-AI\run_all.bat`
   - Стартирай в: `C:\Accounting-AI`
5. Запишете

---

## Отстраняване на проблеми / Troubleshooting

### Грешка: `ModuleNotFoundError: No module named 'openpyxl'`

Използвате грешен Python. Инсталирайте отново:
```
cd C:\Accounting-AI
.\.venv\Scripts\python -m pip install openpyxl pymupdf pypdf
```

### Грешка: `FileNotFoundError: Missing required path(s)`

Папките не са създадени. Върнете се на **Стъпка 5** и изпълнете командите.

### Файл отиде в `02_Review` вместо в `01_Processed`

Името на файла не беше разпознато. Преименувайте го да съдържа ключова дума:
- `invoice`, `faktura`, `receipt`, `bon`, `bank`

### Оценка на доверие (Confidence Score) е под 0.5

Системата не е сигурна. Проверете колона `Notes` и попълнете липсващите полета ръчно.

### Logs — къде да видя какво е направила програмата

Отворете файла `Logs\run_log.txt` с Notepad. Всеки ред показва какво е класифицирано, преименувано и преместено.

---

## Какво НЕ прави тази програма / Limitations

- ❌ **НЕ** контира директно в Delta Pro
- ❌ **НЕ** презаписва счетоводни данни
- ❌ **НЕ** подава декларации
- ❌ **НЕ** изчислява заплати (ТРЗ)
- ❌ **НЕ** има графичен интерфейс — работи с файлове и Excel

> ⚠️ Ръчната проверка в `02_Review` е **задължителна** преди импорт в Delta Pro.

---

*Версия: 1.1.2 — Март 2026*
*Съвместимо с Microinvest Delta Pro + ТРЗ Pro*
