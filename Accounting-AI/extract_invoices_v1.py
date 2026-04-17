#!/usr/bin/env python3
"""MVP v1.1 invoice extraction / извличане на фактури към review Excel.

Reads standardized filenames and, for PDF invoices, attempts real text extraction
to improve supplier/date/invoice number/amount detection.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

try:
    import fitz  # type: ignore
except Exception:
    fitz = None

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None


FILENAME_PATTERN = re.compile(
    r"^(?P<client>.+)_(?P<date>\d{4}-\d{2}-\d{2}|UNKNOWNDATE)_(?P<dtype>Invoice|Receipt|Bank|Other)_(?P<counterparty>[^_]+)_(?P<amount>[^_]+?)(?:_(?P<dup>\d+))?$",
    re.IGNORECASE,
)

SUPPORTED_INVOICE_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def write_log(log_file: Path, line: str) -> None:
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ensure_log_header(log_file: Path) -> None:
    if not log_file.exists() or log_file.stat().st_size == 0:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write("# Accounting AI Run Log / Дневник на изпълнение\n")
            fh.write("# Format / Формат: YYYY-MM-DD HH:MM [Action details / Детайли]\n")


def parse_amount(value: str) -> float | None:
    if value.lower() == "unknown":
        return None
    normalized = value.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def normalize_dtype(dtype: str) -> str:
    lower = dtype.lower()
    if lower == "invoice":
        return "Invoice"
    if lower == "receipt":
        return "Receipt"
    if lower == "bank":
        return "Bank"
    return "Other"


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _to_iso_date(date_value: str) -> str:
    date_value = date_value.strip()
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _parse_money(value: str) -> float | None:
    cleaned = value.replace(" ", "").replace("\u00a0", "")
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if cleaned.count(".") > 1:
        # Keep last decimal separator and strip older ones (e.g. 1.234.56)
        left, right = cleaned.rsplit(".", 1)
        cleaned = left.replace(".", "") + "." + right
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_pdf_text(file_path: Path) -> tuple[str, str]:
    """Return (text, backend_used). backend_used is empty if extraction fails."""
    if fitz is not None:
        try:
            chunks: list[str] = []
            with fitz.open(file_path) as doc:
                for page in doc:
                    chunks.append(page.get_text("text"))
            text = "\n".join(chunks)
            if text.strip():
                return text, "PyMuPDF"
        except Exception:
            pass

    if PdfReader is not None:
        try:
            reader = PdfReader(str(file_path))
            chunks = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(chunks)
            if text.strip():
                return text, "pypdf"
        except Exception:
            pass

    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", str(file_path), "-"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout, "pdftotext"
    except FileNotFoundError:
        pass

    return "", ""


def parse_invoice_fields_from_text(text: str) -> dict[str, object]:
    """Extract invoice number/date/supplier/gross amount from BG/EN invoice text."""
    data: dict[str, object] = {
        "Supplier/Customer": "",
        "Invoice Number": "",
        "Invoice Date": "",
        "Gross Amount": None,
    }

    normalized_text = _normalize_space(text)

    supplier_patterns = [
        r"(?:Доставчик|Supplier)\s*[:\-]\s*([^\n\r|]{3,120})",
        r"(?:Издател|Продавач)\s*[:\-]\s*([^\n\r|]{3,120})",
        r"^(?:[A-ZА-Я][A-ZА-Я0-9\-\s\.,]{3,120})(?:\s+(?:ООД|ЕООД|АД|ЕТ|Ltd\.?|LLC))",
    ]
    for pattern in supplier_patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            supplier = _normalize_space(m.group(1) if m.lastindex else m.group(0))
            supplier = supplier.strip(" .,-")
            if len(supplier) >= 3:
                data["Supplier/Customer"] = supplier
                break

    inv_no_patterns = [
        r"(?:Фактура|Invoice)\s*(?:No\.?|N\.?|№)?\s*[:\-]?\s*([A-Za-zА-Яа-я0-9\-/]{3,40})",
        r"(?:Номер|№)\s*[:\-]?\s*([A-Za-zА-Яа-я0-9\-/]{3,40})",
    ]
    for pattern in inv_no_patterns:
        m = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if m:
            data["Invoice Number"] = m.group(1).strip()
            break

    date_patterns = [
        r"(?:Дата|Date)\s*[:\-]?\s*(\d{2}[./-]\d{2}[./-]\d{4})",
        r"(?:Фактура|Invoice).*?(\d{2}[./-]\d{2}[./-]\d{4})",
    ]
    for pattern in date_patterns:
        m = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if m:
            iso = _to_iso_date(m.group(1).replace("/", "."))
            if iso:
                data["Invoice Date"] = iso
                break

    amount_patterns = [
        r"(?:Общо\s+за\s+плащане|Сума\s+за\s+плащане|Крайна\s+сума|Общо|Total\s+due|Grand\s+total)\s*[:\-]?\s*([0-9\s.,]+)",
        r"(?:Сума|Amount|Total)\s*[:\-]?\s*([0-9\s.,]+)\s*(?:лв\.?|BGN|EUR)?",
    ]
    for pattern in amount_patterns:
        for m in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
            parsed = _parse_money(m.group(1))
            if parsed is not None and parsed > 0:
                data["Gross Amount"] = round(parsed, 2)
                return data

    return data


XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XLSX_CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XLSX_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col_letter(col_idx: int) -> str:
    """Convert 0-based column index to Excel column letter (A, B, ..., Z, AA, ...)."""
    result = ""
    idx = col_idx
    while True:
        result = chr(65 + idx % 26) + result
        idx = idx // 26 - 1
        if idx < 0:
            break
    return result


def read_xlsx_headers(template_path: Path) -> list[str]:
    """Read first-row headers from an xlsx template using only stdlib."""
    ns = {"ns": XLSX_NS}
    with zipfile.ZipFile(template_path, "r") as zf:
        # Try shared strings first
        strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            tree = ET.parse(zf.open("xl/sharedStrings.xml"))
            for si in tree.findall(".//ns:si", ns):
                t_el = si.find("ns:t", ns)
                strings.append(t_el.text if t_el is not None and t_el.text else "")

        tree = ET.parse(zf.open("xl/worksheets/sheet1.xml"))
        row1 = tree.find(".//ns:sheetData/ns:row", ns)
        if row1 is None:
            raise ValueError("Template has no rows / Шаблонът няма редове")

        headers: list[str] = []
        for c in row1:
            t_attr = c.get("t", "")
            # Inline string
            if t_attr == "inlineStr":
                is_el = c.find("ns:is/ns:t", ns)
                headers.append(is_el.text if is_el is not None and is_el.text else "")
            # Shared string
            elif t_attr == "s":
                v_el = c.find("ns:v", ns)
                if v_el is not None and v_el.text:
                    headers.append(strings[int(v_el.text)])
                else:
                    headers.append("")
            # Plain value
            else:
                v_el = c.find("ns:v", ns)
                headers.append(v_el.text if v_el is not None and v_el.text else "")
    return headers


def write_xlsx(output_path: Path, headers: list[str], rows: list[list[object]]) -> None:
    """Write a minimal xlsx file with headers and data rows using only stdlib."""
    # Collect all unique strings
    all_strings: list[str] = []
    string_index: dict[str, int] = {}
    for h in headers:
        if h not in string_index:
            string_index[h] = len(all_strings)
            all_strings.append(h)
    for row in rows:
        for val in row:
            if isinstance(val, str) and val not in string_index:
                string_index[val] = len(all_strings)
                all_strings.append(val)

    # Build sharedStrings.xml
    ss_root = ET.Element("sst", xmlns=XLSX_NS, count=str(len(all_strings)), uniqueCount=str(len(all_strings)))
    for s in all_strings:
        si = ET.SubElement(ss_root, "si")
        t = ET.SubElement(si, "t")
        t.text = s

    # Build sheet1.xml
    ws_root = ET.Element("worksheet", xmlns=XLSX_NS)
    sd = ET.SubElement(ws_root, "sheetData")

    # Header row
    r1 = ET.SubElement(sd, "row", r="1")
    for ci, h in enumerate(headers):
        c = ET.SubElement(r1, "c", r=f"{_col_letter(ci)}1", t="s")
        v = ET.SubElement(c, "v")
        v.text = str(string_index[h])

    # Data rows
    for ri, row in enumerate(rows, start=2):
        r_el = ET.SubElement(sd, "row", r=str(ri))
        for ci, val in enumerate(row):
            ref = f"{_col_letter(ci)}{ri}"
            if isinstance(val, (int, float)):
                c = ET.SubElement(r_el, "c", r=ref)
                v = ET.SubElement(c, "v")
                v.text = str(val)
            else:
                s = str(val) if val is not None else ""
                if s not in string_index:
                    string_index[s] = len(all_strings)
                    all_strings.append(s)
                    si = ET.SubElement(ss_root, "si")
                    t = ET.SubElement(si, "t")
                    t.text = s
                    ss_root.set("count", str(len(all_strings)))
                    ss_root.set("uniqueCount", str(len(all_strings)))
                c = ET.SubElement(r_el, "c", r=ref, t="s")
                v = ET.SubElement(c, "v")
                v.text = str(string_index[s])

    # Build minimal xlsx ZIP
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{XLSX_CONTENT_NS}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{XLSX_RELS_NS}">'
        f'<Relationship Id="rId1" Type="{XLSX_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{XLSX_NS}" xmlns:r="{XLSX_REL_NS}">'
        '<sheets><sheet name="Extracted" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{XLSX_RELS_NS}">'
        f'<Relationship Id="rId1" Type="{XLSX_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{XLSX_REL_NS}/sharedStrings" Target="sharedStrings.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + ET.tostring(ws_root, encoding="unicode"),
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + ET.tostring(ss_root, encoding="unicode"),
        )


def resolve_column_map(headers: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    normalized_headers = {h.strip().lower(): idx for idx, h in enumerate(headers)}

    aliases = {
        "Client": ["client"],
        "File Name": ["file name"],
        "Document Type": ["document type", "document type (invoice/receipt)"],
        "Supplier/Customer": ["supplier/customer"],
        "Invoice Number": ["invoice number"],
        "Invoice Date": ["invoice date"],
        "Net Amount": ["net amount"],
        "VAT Amount": ["vat amount"],
        "Gross Amount": ["gross amount"],
        "Currency": ["currency"],
        "Confidence Score": ["confidence score"],
        "Mandatory Review": ["mandatory review", "mandatory check", "manual review required"],
        "Notes": ["notes"],
    }

    for key, names in aliases.items():
        found = None
        for name in names:
            if name in normalized_headers:
                found = normalized_headers[name]
                break
        if found is not None:
            result[key] = found

    required = [
        "Client",
        "File Name",
        "Document Type",
        "Supplier/Customer",
        "Invoice Number",
        "Invoice Date",
        "Net Amount",
        "VAT Amount",
        "Gross Amount",
        "Currency",
        "Confidence Score",
        "Notes",
    ]
    missing = [k for k in required if k not in result]
    if missing:
        raise ValueError("Template is missing required column(s) / Шаблонът няма задължителни колони: " + ", ".join(missing))

    return result


def build_row_values(file_path: Path, client_default: str) -> dict[str, object]:
    file_name = file_path.name
    stem = Path(file_name).stem
    match = FILENAME_PATTERN.match(stem)

    if not match:
        return {
            "Client": client_default,
            "File Name": file_name,
            "Document Type": "Other",
            "Supplier/Customer": "Unknown",
            "Invoice Number": "",
            "Invoice Date": "",
            "Net Amount": "",
            "VAT Amount": "",
            "Gross Amount": "",
            "Currency": "BGN",
            "Confidence Score": 0.30,
            "Notes": (
                "Filename-only extraction / Извличане само по името на файла. "
                "Filename pattern mismatch / Несъответствие с шаблона на име; "
                "manual review required / нужна е ръчна проверка."
            ),
        }

    client = match.group("client")
    date_str = match.group("date")
    dtype = normalize_dtype(match.group("dtype"))
    counterparty = match.group("counterparty")
    amount = parse_amount(match.group("amount"))

    invoice_date = "" if date_str == "UNKNOWNDATE" else date_str
    invoice_number = ""
    mandatory_review = "No"
    source_note_prefix = "Filename-only extraction / Извличане само по името на файла."
    notes: list[str] = []
    if dtype == "Receipt":
        notes.append("Receipt may not have invoice number / Касовият бон може да няма номер на фактура.")
    if dtype not in {"Invoice", "Receipt"}:
        notes.append("Document type is not invoice/receipt / Типът не е фактура/касов бон.")

    if counterparty.lower() == "unknown":
        notes.append("Missing supplier/customer in filename / Липсва доставчик/клиент в името.")

    if amount is None:
        notes.append("Missing or invalid amount in filename / Липсваща или невалидна сума в името.")

    confidence = 0.80
    if invoice_date == "":
        confidence -= 0.20
        notes.append("Missing date in filename / Липсваща дата в името.")
    if counterparty.lower() == "unknown":
        confidence -= 0.20
    if amount is None:
        confidence -= 0.20
    if dtype not in {"Invoice", "Receipt"}:
        confidence = min(confidence, 0.40)

    gross_amount = amount if amount is not None else ""

    ext = file_path.suffix.lower()

    if dtype in {"Invoice", "Receipt"} and ext in IMAGE_EXTENSIONS:
        mandatory_review = "Yes"
        source_note_prefix = "Image-based extraction / Извличане от изображение."
        notes.append(
            "MANDATORY CHECK (image source): verify supplier, date, number, VAT, and total / "
            "ЗАДЪЛЖИТЕЛНА ПРОВЕРКА (изображение): проверете доставчик, дата, номер, ДДС и обща сума."
        )
        confidence = min(confidence, 0.55)

    if dtype in {"Invoice", "Receipt"} and ext == ".pdf":
        pdf_text, backend = extract_pdf_text(file_path)
        if pdf_text:
            extracted = parse_invoice_fields_from_text(pdf_text)
            found_supplier = str(extracted.get("Supplier/Customer") or "").strip()
            found_inv_no = str(extracted.get("Invoice Number") or "").strip()
            found_date = str(extracted.get("Invoice Date") or "").strip()
            found_amount = extracted.get("Gross Amount")

            if found_supplier:
                counterparty = found_supplier
            if found_inv_no:
                invoice_number = found_inv_no
            if found_date:
                invoice_date = found_date
            if isinstance(found_amount, float):
                gross_amount = found_amount

            notes.append(
                f"PDF text parsed ({backend}) / Обработен PDF текст ({backend})."
            )
            source_note_prefix = "Filename + PDF text extraction / Извличане по име на файл + PDF текст."
            confidence = min(0.98, confidence + 0.10)
        else:
            notes.append(
                "PDF text extraction unavailable/empty / Липсва извличане на текст от PDF или текстът е празен."
            )

    return {
        "Client": client or client_default,
        "File Name": file_name,
        "Document Type": dtype,
        "Supplier/Customer": counterparty,
        "Invoice Number": invoice_number,
        "Invoice Date": invoice_date,
        "Net Amount": "",
        "VAT Amount": "",
        "Gross Amount": gross_amount,
        "Currency": "BGN",
        "Confidence Score": max(0.0, round(confidence, 2)),
        "Mandatory Review": mandatory_review,
        "Notes": source_note_prefix + " " + " ".join(notes).strip(),
    }


def run(base_dir: Path, client_name: str) -> int:
    client_dir = base_dir / "Clients" / client_name
    processed_dir = client_dir / "01_Processed"
    review_dir = client_dir / "02_Review"
    templates_dir = base_dir / "Templates"
    template_file = templates_dir / "extracted_invoices.xlsx"
    output_file = review_dir / "extracted_invoices.xlsx"
    log_file = base_dir / "Logs" / "run_log.txt"

    required_paths = [processed_dir, review_dir, template_file, log_file.parent]
    missing = [p for p in required_paths if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required path(s) / Липсват задължителни пътища: " + ", ".join(str(m) for m in missing))

    ensure_log_header(log_file)

    if output_file.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = output_file.with_name(f"extracted_invoices_BACKUP_{ts}.xlsx")
        shutil.copy2(output_file, backup)
        write_log(log_file, f"{now_str()} Backup / Резервно копие: {output_file.name} -> {backup.name}")

    headers = read_xlsx_headers(template_file)
    col_map = resolve_column_map([str(h) for h in headers])
    if "Mandatory Review" not in col_map:
        write_log(
            log_file,
            (
                f"{now_str()} Warning / Предупреждение: Template missing 'Mandatory Review' column; "
                "processing continues without that field / Шаблонът няма колона 'Mandatory Review'; "
                "обработката продължава без това поле."
            ),
        )

    files = [p for p in processed_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.name.lower())

    extracted_count = 0
    all_rows: list[list[object]] = []
    for file_path in files:
        try:
            row_data = build_row_values(file_path, client_name)
            if row_data["Document Type"] not in {"Invoice", "Receipt"}:
                continue
            if file_path.suffix.lower() not in SUPPORTED_INVOICE_EXTENSIONS:
                write_log(
                    log_file,
                    f"{now_str()} Skipped unsupported extraction format / Пропуснат неподдържан формат за извличане: {file_path.name}",
                )
                continue

            row: list[object] = ["" for _ in headers]
            for key, value in row_data.items():
                if key not in col_map:
                    continue
                idx = col_map[key]
                row[idx] = value

            all_rows.append(row)
            extracted_count += 1

            write_log(log_file, f"{now_str()} Extracted invoice row / Извлечен ред от {file_path.name} -> {output_file.name}")
        except Exception as exc:
            write_log(
                log_file,
                f"{now_str()} ERROR extracting / ГРЕШКА при извличане на {file_path.name}: {exc}",
            )

    try:
        write_xlsx(output_file, headers, all_rows)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot save {output_file} / Не може да се запише файлът. "
            "It may be open in Excel / Файлът може да е отворен в Excel."
        ) from exc
    write_log(log_file, f"{now_str()} Invoice extraction completed / Извличането приключи: {extracted_count} row(s)/реда за {client_name}")
    return extracted_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Accounting-AI MVP invoice extraction runner / Стартиране на извличането на фактури")
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Path to Accounting-AI root folder / Път до основната папка (по подразбиране: текущата)",
    )
    parser.add_argument(
        "--client",
        default="Client_A",
        help="Client folder name under Clients/ / Име на клиентска папка в Clients/ (по подразбиране: Client_A)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.client.strip() == "":
        raise ValueError("--client cannot be empty / --client не може да е празно")

    count = run(base_dir=base_dir, client_name=args.client)
    print(f"Extracted / Извлечени: {count} invoice/receipt row(s) за {args.client}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
