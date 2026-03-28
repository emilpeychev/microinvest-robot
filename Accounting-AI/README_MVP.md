# Accounting-AI MVP (v1) / Двуезичен (EN/BG)

This MVP currently implements / Този MVP в момента включва:
- intake from `00_Incoming` / вход от `00_Incoming`
- classification by extension/filename / класификация по разширение/име
- safe rename / безопасно преименуване
- move to `01_Processed`, `02_Review`, or `04_Unsupported` / преместване към `01_Processed`, `02_Review` или `04_Unsupported`
- append action logs to `Logs/run_log.txt` / запис на действия в `Logs/run_log.txt`
- generation of `02_Review/extracted_invoices.xlsx` from processed files / генериране на `02_Review/extracted_invoices.xlsx` от обработените файлове
- PDF invoice text reading when available (PyMuPDF, pypdf, or pdftotext fallback) / четене на текст от PDF фактури при наличност (PyMuPDF, pypdf или резервно pdftotext)

Accepted extraction formats / Поддържани формати за извличане:
- PDF: `.pdf`
- Images: `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.bmp`, `.webp`

Mandatory checks for image rows / Задължителни проверки за редове от изображения:
- Every image-based invoice/receipt row is marked in `Notes` as mandatory review required.
- Confidence is capped to ensure human verification before posting.
- `Mandatory Review` column is auto-filled when present in the template: `Yes` for image formats, `No` for PDF.

PDF extraction dependencies / Зависимости за извличане от PDF:
- Python packages: `openpyxl`, `pymupdf`, `pypdf`
- Linux package for fallback: `poppler-utils` (`pdftotext`)

## Pilot Client / Пилотен клиент
Use one pilot client first / Използвайте първо един пилотен клиент: `Client_A`

## Run / Стартиране
From workspace root / От корена на проекта:

```bash
.venv/bin/python Accounting-AI/intake_v1.py --base-dir Accounting-AI --client Client_A
```

Invoice extraction (from processed files) / Извличане на фактури (от обработени файлове):

```bash
.venv/bin/python Accounting-AI/extract_invoices_v1.py --base-dir Accounting-AI --client Client_A
```

One-command runner / Стартиране с една команда:

```bash
./Accounting-AI/run_all.sh Accounting-AI Client_A
```

Dry run (no file move) / Тестов режим (без преместване):

```bash
.venv/bin/python Accounting-AI/intake_v1.py --base-dir Accounting-AI --client Client_A --dry-run
```

Run tests / Стартиране на тестове:

```bash
./Accounting-AI/run_tests.sh unit
```

Run full tests (with workbook integration test) / Пълни тестове (с интеграционен тест за Excel):

```bash
./Accounting-AI/run_tests.sh full
```

Run integration tests only / Само интеграционни тестове:

```bash
./Accounting-AI/run_tests.sh integration
```

## Naming Format / Формат на именуване
`CLIENT_YYYY-MM-DD_TYPE_COUNTERPARTY_AMOUNT.ext`

If data is missing, placeholders are used / Ако липсват данни, се използват заместители (for example / например `UNKNOWNDATE`, `Unknown`).

## Scope Boundaries / Граници
Allowed in this MVP / Разрешено в този MVP:
- sort / сортиране
- rename / преименуване
- move / преместване
- log / логване

Not allowed in this MVP / Неразрешено в този MVP:
- posting directly to Delta Pro / директно контиране в Delta Pro
- final ledger overwrite / презапис на окончателни счетоводни данни
- tax declaration submission / подаване на декларации
- payroll/TRZ automation / автоматизация на ТРЗ
- schedules automation / автоматизация на графици
