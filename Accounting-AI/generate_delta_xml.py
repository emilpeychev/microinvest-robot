#!/usr/bin/env python3
"""Generate Delta Pro XML import file from extracted invoice data.

Reads the review spreadsheet (02_Review/extracted_invoices.xlsx) produced by
extract_invoices_v1.py and generates a Delta Pro-compatible XML file that can
be imported via Операции → Импорт на операции → Импорт от XML.

Генерира XML файл за импорт в Delta Pro от извлечените фактурни данни.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# xlsx reader (reused from extract_invoices_v1)
# ---------------------------------------------------------------------------
XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _read_xlsx_rows(xlsx_path: Path) -> list[dict[str, str]]:
    """Read all rows from sheet1 of an xlsx file, return list of dicts keyed by header."""
    ns = {"ns": XLSX_NS}
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            tree = ET.parse(zf.open("xl/sharedStrings.xml"))
            for si in tree.findall(".//ns:si", ns):
                t_el = si.find("ns:t", ns)
                strings.append(t_el.text if t_el is not None and t_el.text else "")

        tree = ET.parse(zf.open("xl/worksheets/sheet1.xml"))
        all_rows = tree.findall(".//ns:sheetData/ns:row", ns)
        if not all_rows:
            return []

        def _cell_value(cell: ET.Element) -> str:
            t_attr = cell.get("t", "")
            if t_attr == "inlineStr":
                is_el = cell.find("ns:is/ns:t", ns)
                return is_el.text if is_el is not None and is_el.text else ""
            if t_attr == "s":
                v_el = cell.find("ns:v", ns)
                if v_el is not None and v_el.text:
                    idx = int(v_el.text)
                    return strings[idx] if idx < len(strings) else ""
                return ""
            v_el = cell.find("ns:v", ns)
            return v_el.text if v_el is not None and v_el.text else ""

        def _col_index(ref: str) -> int:
            col_str = re.match(r"([A-Z]+)", ref)
            if not col_str:
                return 0
            result = 0
            for ch in col_str.group(1):
                result = result * 26 + (ord(ch) - 64)
            return result - 1

        # Read headers from row 1
        headers: list[str] = []
        header_row = all_rows[0]
        max_col = 0
        for cell in header_row:
            ci = _col_index(cell.get("r", "A1"))
            while len(headers) <= ci:
                headers.append("")
            headers[ci] = _cell_value(cell).strip()
            max_col = max(max_col, ci)

        # Read data rows
        result: list[dict[str, str]] = []
        for row_el in all_rows[1:]:
            vals: list[str] = [""] * (max_col + 1)
            for cell in row_el:
                ci = _col_index(cell.get("r", "A1"))
                if ci <= max_col:
                    vals[ci] = _cell_value(cell)
            row_dict = {headers[i]: vals[i] for i in range(len(headers)) if headers[i]}
            # Skip entirely empty rows
            if any(v.strip() for v in row_dict.values()):
                result.append(row_dict)
        return result


# ---------------------------------------------------------------------------
# Amount helpers
# ---------------------------------------------------------------------------

def _parse_amount(value: str) -> float | None:
    """Parse a numeric string, tolerating comma decimals."""
    if not value or value.strip().lower() in ("", "unknown"):
        return None
    cleaned = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if cleaned.count(".") > 1:
        left, right = cleaned.rsplit(".", 1)
        cleaned = left.replace(".", "") + "." + right
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _fmt_amount(value: float) -> str:
    """Format amount with 6 decimal places as Delta Pro expects."""
    return f"{value:.6f}"


# ---------------------------------------------------------------------------
# Account mapping
# ---------------------------------------------------------------------------

def load_account_map(rules_dir: Path) -> dict:
    """Load account_map.json from Rules directory."""
    map_path = rules_dir / "account_map.json"
    if not map_path.exists():
        raise FileNotFoundError(
            f"Account map not found / Не е намерена картата на сметките: {map_path}"
        )
    with map_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _match_expense(supplier: str, doc_type: str, account_map: dict) -> tuple[str, str]:
    """Return (expense_account, term_prefix) by matching keywords against supplier name."""
    search_text = (supplier + " " + doc_type).lower()
    for rule in account_map.get("expense_rules", []):
        kw = rule["keyword"].lower()
        if kw in search_text:
            return rule["account"], rule.get("term_prefix", account_map.get("default_term_prefix", "Покупка"))
    return (
        account_map.get("default_expense_account", "602/9"),
        account_map.get("default_term_prefix", "Покупка"),
    )


# ---------------------------------------------------------------------------
# XML generation
# ---------------------------------------------------------------------------

TRANSFER_NS = "urn:Transfer"


def _build_accounting_element(
    *,
    number: int,
    accounting_date: str,
    doc_date: str,
    doc_number: str,
    doc_type_code: str,
    company_name: str,
    company_bulstat: str,
    company_vat: str,
    term: str,
    reference: str,
    vat_term: str,
    details: list[tuple[str, str, float]],
) -> ET.Element:
    """Build a single <Accounting> element.

    details: list of (account_number, direction, amount) tuples.
    """
    acc = ET.Element("Accounting")
    acc.set("AccountingDate", accounting_date)
    acc.set("DueDate", accounting_date)
    acc.set("Number", f"{number:010d}")
    acc.set("Reference", reference)
    acc.set("OptionalReference", "")
    acc.set("Term", term)
    acc.set("Vies", "1")
    acc.set("ViesMonth", accounting_date)

    doc = ET.SubElement(acc, "Document")
    doc.set("Date", doc_date)
    doc.set("Number", doc_number)
    doc.set("DocumentType", doc_type_code)

    if company_name:
        company = ET.SubElement(acc, "Company")
        company.set("Name", company_name)
        if company_bulstat:
            company.set("Bulstat", company_bulstat)
        if company_vat:
            company.set("VatNumber", company_vat)
        ET.SubElement(company, "BankAccounts")

    ad_parent = ET.SubElement(acc, "AccountingDetails")
    for acct_num, direction, amount in details:
        ad = ET.SubElement(ad_parent, "AccountingDetail")
        ad.set("AccountNumber", acct_num)
        ad.set("Direction", direction)
        ad.set("VatTerm", vat_term)
        ad.set("Amount", _fmt_amount(amount))

    return acc


def generate_xml(
    rows: list[dict[str, str]],
    account_map: dict,
    start_number: int = 1,
) -> ET.Element:
    """Generate Delta Pro TransferData XML from extracted invoice rows."""
    vat_rate = account_map.get("vat_rate", 0.20)
    supplier_acct = account_map.get("supplier_account", "401/1")
    vat_input_acct = account_map.get("vat_input_account", "453/1")

    root = ET.Element("TransferData")
    root.set("xmlns", TRANSFER_NS)
    accountings = ET.SubElement(root, "Accountings")

    current_number = start_number

    for row in rows:
        doc_type = (
            row.get("Document Type", "")
            or row.get("Document Type (Invoice/Receipt)", "")
        ).strip()
        if doc_type not in ("Invoice", "Receipt"):
            continue

        supplier = row.get("Supplier/Customer", "").strip()
        invoice_number = row.get("Invoice Number", "").strip()
        invoice_date = row.get("Invoice Date", "").strip()
        gross_str = row.get("Gross Amount", "").strip()

        gross = _parse_amount(gross_str)
        if gross is None or gross <= 0:
            continue

        # Normalise date to YYYY-MM-DD
        if not re.match(r"\d{4}-\d{2}-\d{2}$", invoice_date):
            # Try DD.MM.YYYY
            for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    invoice_date = datetime.strptime(invoice_date, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        if not re.match(r"\d{4}-\d{2}-\d{2}$", invoice_date):
            invoice_date = datetime.now().strftime("%Y-%m-%d")

        if not invoice_number:
            invoice_number = f"{current_number:010d}"

        expense_account, term_prefix = _match_expense(supplier, doc_type, account_map)
        term = f"{term_prefix} {supplier}" if supplier and supplier.lower() != "unknown" else term_prefix

        # Determine VAT handling
        # Check if supplier has VatNumber pattern (starts with BG + digits)
        # For now: 20% VAT is default for invoices, 0% for receipts
        has_vat = (doc_type == "Invoice")

        if has_vat:
            net = round(gross / (1 + vat_rate), 2)
            vat = round(gross - net, 2)
            # Purchase entry: Dt expense (net) + Dt 453/1 (VAT) / Ct 401/1 (gross)
            details: list[tuple[str, str, float]] = [
                (supplier_acct, "Credit", gross),
                (expense_account, "Debit", net),
                (vat_input_acct, "Debit", vat),
            ]
            vat_term = "2"  # Покупка
            doc_type_code = "1"  # Фактура
        else:
            # Receipt — no VAT split, full amount to expense, VatTerm=3
            details = [
                (supplier_acct, "Credit", gross),
                (expense_account, "Debit", gross),
            ]
            vat_term = "3"
            doc_type_code = "1"

        acc_el = _build_accounting_element(
            number=current_number,
            accounting_date=invoice_date,
            doc_date=invoice_date,
            doc_number=invoice_number,
            doc_type_code=doc_type_code,
            company_name=supplier if supplier.lower() != "unknown" else "",
            company_bulstat="",
            company_vat="",
            term=term,
            reference="",
            vat_term=vat_term,
            details=details,
        )
        accountings.append(acc_el)
        current_number += 1

    return root


# ---------------------------------------------------------------------------
# Pretty print helper (stdlib doesn't have indent until 3.9)
# ---------------------------------------------------------------------------

def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Add whitespace indentation to XML tree for readability."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():  # noqa: F821 — child is last from loop
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def write_xml(root: ET.Element, output_path: Path) -> None:
    """Write XML tree to file with declaration and indentation."""
    _indent_xml(root)
    tree = ET.ElementTree(root)
    with output_path.open("wb") as fh:
        tree.write(fh, encoding="utf-8", xml_declaration=True)


def run(base_dir: Path, client_name: str) -> int:
    """Read extracted invoices and generate Delta Pro import XML.

    Returns the number of accounting entries generated.
    """
    client_dir = base_dir / "Clients" / client_name
    review_dir = client_dir / "02_Review"
    rules_dir = base_dir / "Rules"
    log_file = base_dir / "Logs" / "run_log.txt"

    xlsx_path = review_dir / "extracted_invoices.xlsx"
    output_path = review_dir / "delta_import.xml"

    if not xlsx_path.exists():
        raise FileNotFoundError(
            f"Extracted invoices not found / Не е намерен файлът с извлечените фактури: {xlsx_path}\n"
            "Run extract_invoices_v1.py first / Стартирайте първо extract_invoices_v1.py"
        )

    account_map = load_account_map(rules_dir)
    rows = _read_xlsx_rows(xlsx_path)

    if not rows:
        _write_log(log_file, f"{_now()} Delta import: no invoice rows found / Няма редове с фактури")
        return 0

    root = generate_xml(rows, account_map)
    accs_el = root.find("Accountings")
    entry_count = len(accs_el) if accs_el is not None else 0

    if entry_count == 0:
        _write_log(log_file, f"{_now()} Delta import: no valid entries generated / Няма генерирани валидни записи")
        return 0

    write_xml(root, output_path)
    _write_log(
        log_file,
        f"{_now()} Delta Pro XML generated / Генериран XML за Delta Pro: "
        f"{entry_count} entries/записа -> {output_path.name}",
    )
    return entry_count


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _write_log(log_file: Path, line: str) -> None:
    if log_file.parent.exists():
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Delta Pro XML import from extracted invoices / "
        "Генериране на XML за импорт в Delta Pro"
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Path to Accounting-AI root / Път до основната папка (по подразбиране: .)",
    )
    parser.add_argument(
        "--client",
        default="Client_A",
        help="Client folder name / Име на клиентска папка (по подразбиране: Client_A)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    count = run(base_dir=base_dir, client_name=args.client)
    print(f"Delta Pro XML: {count} accounting entries / счетоводни записа за {args.client}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
