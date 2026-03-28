#!/usr/bin/env python3
"""Unit tests for intake/extract policy behavior."""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from test_utils import load_module

intake = load_module("intake_v1", "intake_v1.py")

# Keep unit tests runnable even when openpyxl is unavailable in system Python.
try:
    import openpyxl  # noqa: F401
except Exception:
    import sys

    fake_openpyxl = types.SimpleNamespace(load_workbook=lambda *_args, **_kwargs: None)
    sys.modules["openpyxl"] = fake_openpyxl

extract = load_module("extract_invoices_v1", "extract_invoices_v1.py")


class IntakeFormatTests(unittest.TestCase):
    def test_extended_image_formats_are_accepted_as_document_like(self):
        for ext in [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"]:
            doc_type, reason = intake.detect_doc_type(f"scanfile_abc{ext}", ext)
            self.assertEqual(doc_type, "other")
            self.assertEqual(reason, "unrecognized-document")

    def test_unsupported_extensions_still_go_to_unsupported(self):
        doc_type, reason = intake.detect_doc_type("random_file.docx", ".docx")
        self.assertEqual(doc_type, "other")
        self.assertEqual(reason, "unsupported-extension")


class ExtractRowPolicyTests(unittest.TestCase):
    def test_image_row_requires_mandatory_review(self):
        file_path = Path("Client_A_2026-03-28_Receipt_Shell_15.50.jpg")
        row = extract.build_row_values(file_path=file_path, client_default="Client_A")

        self.assertEqual(row["Document Type"], "Receipt")
        self.assertEqual(row["Mandatory Review"], "Yes")
        self.assertLessEqual(row["Confidence Score"], 0.55)
        self.assertIn("MANDATORY CHECK", row["Notes"])

    def test_pdf_row_defaults_to_non_mandatory_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "Client_A_2026-03-28_Invoice_Demo_120.00.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\\n%EOF\\n")

            row = extract.build_row_values(file_path=pdf_path, client_default="Client_A")

        self.assertEqual(row["Document Type"], "Invoice")
        self.assertEqual(row["Mandatory Review"], "No")
        self.assertGreaterEqual(row["Confidence Score"], 0.6)

    def test_supported_invoice_extensions_include_pdf_and_images(self):
        expected = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
        self.assertEqual(extract.SUPPORTED_INVOICE_EXTENSIONS, expected)


if __name__ == "__main__":
    unittest.main()
