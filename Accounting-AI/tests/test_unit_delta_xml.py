#!/usr/bin/env python3
"""Tests for generate_delta_xml.py / Тестове за генератора на Delta Pro XML."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import generate_delta_xml as gdx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MAP = {
    "expense_rules": [
        {"keyword": "шел", "account": "601/3", "term_prefix": "Покупка гориво"},
        {"keyword": "shell", "account": "601/3", "term_prefix": "Покупка гориво"},
        {"keyword": "виваком", "account": "602/4", "term_prefix": "Покупка тел. услуги"},
    ],
    "default_expense_account": "602/9",
    "default_term_prefix": "Покупка",
    "vat_rate": 0.20,
    "supplier_account": "401/1",
    "vat_input_account": "453/1",
    "vat_output_account": "453/2",
    "customer_account": "411",
    "cash_account": "501",
    "bank_account": "503/1",
}


def _make_test_xlsx(path: Path, rows: list[dict[str, str]]) -> None:
    """Create a minimal xlsx with the standard headers and given rows."""
    headers = [
        "Client", "File Name", "Document Type", "Supplier/Customer",
        "Invoice Number", "Invoice Date", "Net Amount", "VAT Amount",
        "Gross Amount", "Currency", "Confidence Score", "Notes", "Mandatory Review",
    ]

    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    ns_rels = "http://schemas.openxmlformats.org/package/2006/relationships"

    # Collect all strings
    all_strings: list[str] = []
    idx_map: dict[str, int] = {}
    for h in headers:
        if h not in idx_map:
            idx_map[h] = len(all_strings)
            all_strings.append(h)
    for row in rows:
        for h in headers:
            val = row.get(h, "")
            if val and val not in idx_map:
                idx_map[val] = len(all_strings)
                all_strings.append(val)

    # sharedStrings
    ss_root = ET.Element("sst", xmlns=ns_main)
    for s in all_strings:
        si = ET.SubElement(ss_root, "si")
        t = ET.SubElement(si, "t")
        t.text = s

    # sheet
    def _col(i: int) -> str:
        r = ""
        x = i
        while True:
            r = chr(65 + x % 26) + r
            x = x // 26 - 1
            if x < 0:
                break
        return r

    ws = ET.Element("worksheet", xmlns=ns_main)
    sd = ET.SubElement(ws, "sheetData")
    r1 = ET.SubElement(sd, "row", r="1")
    for ci, h in enumerate(headers):
        c = ET.SubElement(r1, "c", r=f"{_col(ci)}1", t="s")
        v = ET.SubElement(c, "v")
        v.text = str(idx_map[h])

    for ri, row in enumerate(rows, start=2):
        r_el = ET.SubElement(sd, "row", r=str(ri))
        for ci, h in enumerate(headers):
            val = row.get(h, "")
            ref = f"{_col(ci)}{ri}"
            if val not in idx_map:
                idx_map[val] = len(all_strings)
                all_strings.append(val)
                si = ET.SubElement(ss_root, "si")
                t = ET.SubElement(si, "t")
                t.text = val
            c = ET.SubElement(r_el, "c", r=ref, t="s")
            v = ET.SubElement(c, "v")
            v.text = str(idx_map[val])

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        ct = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Types xmlns="{ns_ct}">'
            f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            f'<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            f'</Types>'
        )
        rels = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{ns_rels}">'
            f'<Relationship Id="rId1" Type="{ns_rel}/officeDocument" Target="xl/workbook.xml"/>'
            f'</Relationships>'
        )
        wb = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{ns_main}" xmlns:r="{ns_rel}">'
            f'<sheets><sheet name="Extracted" sheetId="1" r:id="rId1"/></sheets>'
            f'</workbook>'
        )
        wb_rels = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{ns_rels}">'
            f'<Relationship Id="rId1" Type="{ns_rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{ns_rel}/sharedStrings" Target="sharedStrings.xml"/>'
            f'</Relationships>'
        )
        zf.writestr("[Content_Types].xml", ct)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(ws, encoding="unicode"),
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(ss_root, encoding="unicode"),
        )


def _setup_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create standard directory structure for testing, return (base, review, rules)."""
    review = tmp_path / "Clients" / "TestClient" / "02_Review"
    review.mkdir(parents=True)
    rules = tmp_path / "Rules"
    rules.mkdir()
    logs = tmp_path / "Logs"
    logs.mkdir()
    # Write account map
    with (rules / "account_map.json").open("w", encoding="utf-8") as fh:
        json.dump(SAMPLE_MAP, fh)
    return tmp_path, review, rules


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generate_xml_purchase_with_vat():
    """Purchase invoice → Dt expense + Dt 453/1 / Ct 401/1, VatTerm=2."""
    rows = [
        {
            "Document Type": "Invoice",
            "Supplier/Customer": "ШЕЛ БЪЛГАРИЯ ЕАД",
            "Invoice Number": "2008940031",
            "Invoice Date": "2025-01-10",
            "Gross Amount": "223.49",
        },
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    accs = root.find("Accountings")
    assert accs is not None
    assert len(accs) == 1

    acc = accs[0]
    assert acc.get("AccountingDate") == "2025-01-10"
    assert acc.get("Term") == "Покупка гориво ШЕЛ БЪЛГАРИЯ ЕАД"

    doc = acc.find("Document")
    assert doc.get("DocumentType") == "1"
    assert doc.get("Number") == "2008940031"

    company = acc.find("Company")
    assert company.get("Name") == "ШЕЛ БЪЛГАРИЯ ЕАД"

    details = acc.find("AccountingDetails")
    d_list = list(details)
    assert len(d_list) == 3

    # Ct 401/1 = gross
    credit = [d for d in d_list if d.get("Direction") == "Credit"]
    assert len(credit) == 1
    assert credit[0].get("AccountNumber") == "401/1"
    assert float(credit[0].get("Amount")) == 223.49

    # Dt expense 601/3 = net
    debits = [d for d in d_list if d.get("Direction") == "Debit"]
    assert len(debits) == 2
    expense_debit = [d for d in debits if d.get("AccountNumber") == "601/3"]
    vat_debit = [d for d in debits if d.get("AccountNumber") == "453/1"]
    assert len(expense_debit) == 1
    assert len(vat_debit) == 1

    net = round(223.49 / 1.20, 2)
    vat = round(223.49 - net, 2)
    assert abs(float(expense_debit[0].get("Amount")) - net) < 0.01
    assert abs(float(vat_debit[0].get("Amount")) - vat) < 0.01

    # All VatTerm = 2
    for d in d_list:
        assert d.get("VatTerm") == "2"


def test_generate_xml_receipt_no_vat():
    """Receipt → VatTerm=3, no VAT split."""
    rows = [
        {
            "Document Type": "Receipt",
            "Supplier/Customer": "Магазин",
            "Invoice Number": "R001",
            "Invoice Date": "2025-03-15",
            "Gross Amount": "50.00",
        },
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    accs = root.find("Accountings")
    assert len(accs) == 1
    details = list(accs[0].find("AccountingDetails"))
    assert len(details) == 2  # No 453/1 line
    for d in details:
        assert d.get("VatTerm") == "3"


def test_generate_xml_skips_non_invoice():
    """Bank/Other document types are skipped."""
    rows = [
        {"Document Type": "Bank", "Supplier/Customer": "X", "Gross Amount": "100"},
        {"Document Type": "Other", "Supplier/Customer": "Y", "Gross Amount": "200"},
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    accs = root.find("Accountings")
    assert len(accs) == 0


def test_generate_xml_skips_zero_amount():
    """Rows with no/zero amount are skipped."""
    rows = [
        {"Document Type": "Invoice", "Supplier/Customer": "X", "Gross Amount": ""},
        {"Document Type": "Invoice", "Supplier/Customer": "Y", "Gross Amount": "0"},
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    assert len(root.find("Accountings")) == 0


def test_generate_xml_default_account():
    """Unknown supplier → default expense account 602/9."""
    rows = [
        {
            "Document Type": "Invoice",
            "Supplier/Customer": "Непозната фирма",
            "Invoice Number": "X1",
            "Invoice Date": "2025-06-01",
            "Gross Amount": "120",
        },
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    details = list(root.find("Accountings")[0].find("AccountingDetails"))
    expense = [d for d in details if d.get("Direction") == "Debit" and d.get("AccountNumber") != "453/1"]
    assert expense[0].get("AccountNumber") == "602/9"


def test_generate_xml_vivacom_match():
    """Виваком → 602/4 telecom account."""
    rows = [
        {
            "Document Type": "Invoice",
            "Supplier/Customer": "Виваком България ЕАД",
            "Invoice Number": "V1",
            "Invoice Date": "2025-01-08",
            "Gross Amount": "58.98",
        },
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    details = list(root.find("Accountings")[0].find("AccountingDetails"))
    expense = [d for d in details if d.get("Direction") == "Debit" and d.get("AccountNumber") != "453/1"]
    assert expense[0].get("AccountNumber") == "602/4"


def test_xml_namespace():
    """Output XML has correct urn:Transfer namespace."""
    rows = [
        {
            "Document Type": "Invoice",
            "Supplier/Customer": "Test",
            "Invoice Number": "1",
            "Invoice Date": "2025-01-01",
            "Gross Amount": "100",
        },
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP)
    assert root.get("xmlns") == "urn:Transfer"


def test_amount_format_six_decimals():
    """Amounts formatted to 6 decimal places."""
    assert gdx._fmt_amount(186.24) == "186.240000"
    assert gdx._fmt_amount(0.6) == "0.600000"
    assert gdx._fmt_amount(1084.81) == "1084.810000"


def test_number_zero_padded():
    """Entry numbers are zero-padded to 10 digits."""
    rows = [
        {
            "Document Type": "Invoice",
            "Supplier/Customer": "Test",
            "Invoice Number": "1",
            "Invoice Date": "2025-01-01",
            "Gross Amount": "100",
        },
    ]
    root = gdx.generate_xml(rows, SAMPLE_MAP, start_number=42)
    acc = root.find("Accountings")[0]
    assert acc.get("Number") == "0000000042"


def test_read_xlsx_and_generate(tmp_path):
    """Integration test: create xlsx → read → generate XML → validate."""
    base, review, rules = _setup_dirs(tmp_path)

    test_rows = [
        {
            "Client": "TestClient",
            "File Name": "test.pdf",
            "Document Type": "Invoice",
            "Supplier/Customer": "ШЕЛ БЪЛГАРИЯ ЕАД",
            "Invoice Number": "2008940031",
            "Invoice Date": "2025-01-10",
            "Net Amount": "",
            "VAT Amount": "",
            "Gross Amount": "223.49",
            "Currency": "BGN",
            "Confidence Score": "0.90",
            "Notes": "",
            "Mandatory Review": "No",
        },
    ]
    _make_test_xlsx(review / "extracted_invoices.xlsx", test_rows)

    count = gdx.run(base, "TestClient")
    assert count == 1

    output = review / "delta_import.xml"
    assert output.exists()

    tree = ET.parse(output)
    root = tree.getroot()
    # Namespace-aware find
    ns = {"t": "urn:Transfer"}
    accs = root.find("t:Accountings", ns)
    if accs is None:
        accs = root.find("Accountings")
    assert accs is not None
    assert len(accs) == 1


def test_multiple_invoices(tmp_path):
    """Multiple invoices → multiple <Accounting> entries with sequential numbers."""
    base, review, rules = _setup_dirs(tmp_path)
    test_rows = [
        {
            "Client": "TestClient",
            "File Name": "a.pdf",
            "Document Type": "Invoice",
            "Supplier/Customer": "Shell",
            "Invoice Number": "A1",
            "Invoice Date": "2025-01-10",
            "Net Amount": "",
            "VAT Amount": "",
            "Gross Amount": "100",
            "Currency": "BGN",
            "Confidence Score": "0.90",
            "Notes": "",
            "Mandatory Review": "No",
        },
        {
            "Client": "TestClient",
            "File Name": "b.pdf",
            "Document Type": "Invoice",
            "Supplier/Customer": "Виваком",
            "Invoice Number": "B2",
            "Invoice Date": "2025-02-15",
            "Net Amount": "",
            "VAT Amount": "",
            "Gross Amount": "60",
            "Currency": "BGN",
            "Confidence Score": "0.85",
            "Notes": "",
            "Mandatory Review": "No",
        },
    ]
    _make_test_xlsx(review / "extracted_invoices.xlsx", test_rows)
    count = gdx.run(base, "TestClient")
    assert count == 2

    tree = ET.parse(review / "delta_import.xml")
    root = tree.getroot()
    ns = {"t": "urn:Transfer"}
    accs = root.find("t:Accountings", ns)
    if accs is None:
        accs = root.find("Accountings")
    assert accs[0].get("Number") == "0000000001"
    assert accs[1].get("Number") == "0000000002"


# ---------------------------------------------------------------------------
# Run with pytest or standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("Running generate_delta_xml tests...")
    failures = 0

    # Unit tests (no filesystem)
    for fn in [
        test_generate_xml_purchase_with_vat,
        test_generate_xml_receipt_no_vat,
        test_generate_xml_skips_non_invoice,
        test_generate_xml_skips_zero_amount,
        test_generate_xml_default_account,
        test_generate_xml_vivacom_match,
        test_xml_namespace,
        test_amount_format_six_decimals,
        test_number_zero_padded,
    ]:
        try:
            fn()
            print(f"  PASS: {fn.__name__}")
        except Exception as exc:
            print(f"  FAIL: {fn.__name__}: {exc}")
            failures += 1

    # Integration tests (need tmp_path)
    for fn in [test_read_xlsx_and_generate, test_multiple_invoices]:
        try:
            with tempfile.TemporaryDirectory() as td:
                fn(Path(td))
            print(f"  PASS: {fn.__name__}")
        except Exception as exc:
            print(f"  FAIL: {fn.__name__}: {exc}")
            failures += 1

    print(f"\n{'All tests passed!' if failures == 0 else f'{failures} test(s) FAILED'}")
    raise SystemExit(failures)
