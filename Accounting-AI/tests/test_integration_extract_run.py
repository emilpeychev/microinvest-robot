#!/usr/bin/env python3
"""Integration tests for extract.run end-to-end workbook generation."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from test_utils import load_module

extract = load_module("extract_invoices_v1_integration", "extract_invoices_v1.py")

XLSX_NS = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _read_xlsx_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read an xlsx file using stdlib and return (headers, data_rows)."""
    with zipfile.ZipFile(path, "r") as zf:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_tree = ET.parse(zf.open("xl/sharedStrings.xml"))
            for si in ss_tree.findall(".//ns:si", XLSX_NS):
                t_el = si.find("ns:t", XLSX_NS)
                strings.append(t_el.text if t_el is not None and t_el.text else "")
        tree = ET.parse(zf.open("xl/worksheets/sheet1.xml"))
        all_rows = tree.findall(".//ns:sheetData/ns:row", XLSX_NS)
        def _cell_value(c) -> str:
            t_attr = c.get("t", "")
            if t_attr == "inlineStr":
                is_el = c.find("ns:is/ns:t", XLSX_NS)
                return is_el.text if is_el is not None and is_el.text else ""
            v_el = c.find("ns:v", XLSX_NS)
            if t_attr == "s" and v_el is not None and v_el.text:
                return strings[int(v_el.text)]
            return v_el.text if v_el is not None and v_el.text else ""
        headers = [_cell_value(c) for c in all_rows[0]] if all_rows else []
        data: list[list[str]] = []
        for row in all_rows[1:]:
            vals = [_cell_value(c) for c in row]
            if any(v for v in vals):
                data.append(vals)
    return headers, data


class ExtractRunIntegrationTests(unittest.TestCase):
    def test_run_generates_review_workbook_with_mandatory_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            client = "Client_IT"

            processed_dir = base_dir / "Clients" / client / "01_Processed"
            review_dir = base_dir / "Clients" / client / "02_Review"
            templates_dir = base_dir / "Templates"
            logs_dir = base_dir / "Logs"

            processed_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            templates_dir.mkdir(parents=True)
            logs_dir.mkdir(parents=True)

            # Create a minimal xlsx template using stdlib
            tmpl_headers = [
                "Client", "File Name", "Document Type (Invoice/Receipt)",
                "Supplier/Customer", "Invoice Number", "Invoice Date",
                "Net Amount", "VAT Amount", "Gross Amount", "Currency",
                "Confidence Score", "Notes", "Mandatory Review",
            ]
            extract.write_xlsx(templates_dir / "extracted_invoices.xlsx", tmpl_headers, [])

            (processed_dir / "Client_IT_2026-03-28_Invoice_Demo_120.00.pdf").write_bytes(b"%PDF-1.4\\n%EOF\\n")
            (processed_dir / "Client_IT_2026-03-28_Receipt_Photo_15.50.jpg").touch()
            (processed_dir / "Client_IT_2026-03-28_Bank_UniCredit_42.00.csv").touch()

            count = extract.run(base_dir=base_dir, client_name=client)
            self.assertEqual(count, 2)

            headers, rows = _read_xlsx_rows(review_dir / "extracted_invoices.xlsx")
            col = {h: i for i, h in enumerate(headers)}

            self.assertEqual(len(rows), 2)
            by_file = {r[col["File Name"]]: r for r in rows}
            self.assertEqual(by_file["Client_IT_2026-03-28_Invoice_Demo_120.00.pdf"][col["Mandatory Review"]], "No")
            self.assertEqual(by_file["Client_IT_2026-03-28_Receipt_Photo_15.50.jpg"][col["Mandatory Review"]], "Yes")


if __name__ == "__main__":
    unittest.main()
