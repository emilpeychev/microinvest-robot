# Incident Report — 2026-04-17

## Summary

Excel output generation failed and runner scripts could not start due to a missing
third-party dependency (`openpyxl`) and a hard requirement on a Python virtual
environment (`.venv`).

---

## Timeline

| Time  | Event |
|-------|-------|
| 10:45 | Attempted to run `extract_invoices_v1.py` — failed with `ModuleNotFoundError: No module named 'openpyxl'` |
| 10:47 | Confirmed `openpyxl` is not installed in the system Python environment |
| 10:48 | Attempted to install `openpyxl` via pip — pip not available / install blocked |
| 10:49 | Decision: remove `openpyxl` dependency entirely, replace with Python stdlib (`zipfile` + `xml.etree`) |
| 10:51 | New stdlib-based xlsx writer implemented and tested — produces valid `Microsoft Excel 2007+` files |
| 10:55 | Updated all documentation (`WINDOWS_SETUP.md`, `INSTALL_AND_USE.md`) to remove `openpyxl` from install instructions |
| 10:55 | Updated all test files (3 files) to remove `openpyxl` imports/mocking — 23/23 tests pass |
| 10:56 | Commit `34ba6ee` pushed to `origin/master` |
| 10:57 | Created 5 realistic test PDF invoices (BG/EN), ran full pipeline (intake → extraction) — 6 rows extracted successfully to Excel |
| 11:02 | User reported `run_all.bat` error: "Python venv not found" |
| 11:03 | Root cause: all runner scripts (`run_all.bat`, `.ps1`, `.sh`) required `.venv` to exist — no fallback to system Python |
| 11:04 | Fix applied: scripts now try `.venv` first, then fall back to system `py` / `python3` / `python` |
| 11:05 | Tested `run_all.sh` — works with system Python, no venv needed |
| 11:05 | Commit `b42d08a` pushed to `origin/master` |

---

## Root Causes

### 1. Hard dependency on `openpyxl`

- `extract_invoices_v1.py` imported `openpyxl` at module level to read/write `.xlsx` files
- On systems without `pip` or where package installation is restricted, this blocks the entire workflow
- The `.xlsx` format is actually a ZIP of XML files — no third-party library needed

### 2. Runner scripts required `.venv`

- `run_all.bat`, `run_all.ps1`, and `run_all.sh` all checked only for `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (Linux)
- If no `.venv` existed, the script printed an error and exited — even if Python was installed system-wide
- After removing `openpyxl`, a venv is no longer needed for any core functionality

---

## Resolution

### Commit `34ba6ee` — Remove openpyxl dependency

**Files changed (6):**

| File | Change |
|------|--------|
| `extract_invoices_v1.py` | Replaced `from openpyxl import load_workbook` with `import zipfile` + `import xml.etree.ElementTree`. Added `read_xlsx_headers()` and `write_xlsx()` functions. Output is standard Office Open XML (`.xlsx`) |
| `WINDOWS_SETUP.md` | Removed `openpyxl` from pip install commands, verify checks, and troubleshooting |
| `INSTALL_AND_USE.md` | Same — Windows + Linux sections updated |
| `tests/test_integration_extract_run.py` | Removed `openpyxl` import, uses stdlib XML to read/verify xlsx output |
| `tests/test_unit_intake_extract.py` | Removed `openpyxl` mock/shim |
| `tests/test_unit_pdf_parser.py` | Removed `openpyxl` mock/shim |

### Commit `b42d08a` — Runner scripts fallback

**Files changed (3):**

| File | Change |
|------|--------|
| `run_all.bat` | Added fallback: tries `py`, then `python` if no `.venv` found |
| `run_all.ps1` | Added fallback: tries `py`, then `python` via `Get-Command` |
| `run_all.sh` | Added fallback: tries `python3`, then `python` via `command -v` |

---

## Verification

- **23/23 unit and integration tests pass** (no `openpyxl` required anywhere)
- **Full pipeline test**: 5 PDF invoices created → intake processed 6 files → Excel generated with 6 rows
- **Output file type**: `file` command confirms `Microsoft Excel 2007+`
- **Runner script**: `run_all.sh` executes successfully with system Python (no `.venv`)

---

## Impact

- **Severity**: Medium — blocked all Excel output and script execution on systems without venv
- **Users affected**: Any user following the setup guide who skipped venv creation or couldn't install pip packages
- **Data loss**: None — no data was corrupted or lost
- **Downtime**: None — development/testing environment only

---

## Lessons Learned

1. **Minimize external dependencies** — if stdlib can do the job, don't add a pip dependency
2. **Always have a fallback** — runner scripts should degrade gracefully instead of failing hard
3. **Test on bare systems** — verify the workflow works with just Python installed, no venv, no pip

---

## Current Required Dependencies

| Dependency | Required? | Purpose |
|------------|-----------|---------|
| Python 3.10+ | **Yes** | Core runtime |
| `pymupdf` (fitz) | Optional | Better PDF text extraction |
| `pypdf` | Optional | Fallback PDF text extraction |
| `pdftotext` (poppler) | Optional | Second fallback PDF text extraction |
| `openpyxl` | **No longer needed** | Removed — replaced with stdlib |

> If none of the optional PDF libraries are installed, extraction falls back to filename-only
> parsing (lower confidence scores but still functional).
