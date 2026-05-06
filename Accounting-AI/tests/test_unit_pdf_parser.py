#!/usr/bin/env python3
"""Unit tests for extract_invoices_v1 PDF text parser."""

from __future__ import annotations

import unittest

from test_utils import load_module

extract = load_module("extract_invoices_v1_parser_test", "extract_invoices_v1.py")


class ParseInvoiceFieldsTests(unittest.TestCase):
    """Tests for parse_invoice_fields_from_text() covering BG/EN invoice text."""

    def test_bg_invoice_all_fields(self):
        text = (
            "Фактура № 0000012345\n"
            "Дата: 15.03.2026\n"
            "Доставчик: ЛИДЛ БЪЛГАРИЯ ЕООД\n"
            "Общо за плащане: 1 234,56 лв.\n"
        )
        result = extract.parse_invoice_fields_from_text(text)
        self.assertEqual(result["Invoice Number"], "0000012345")
        self.assertEqual(result["Invoice Date"], "2026-03-15")
        self.assertEqual(result["Supplier/Customer"], "ЛИДЛ БЪЛГАРИЯ ЕООД")
        self.assertEqual(result["Gross Amount"], 1234.56)

    def test_en_invoice_all_fields(self):
        text = (
            "Invoice No: INV-2026-789\n"
            "Date: 20.01.2026\n"
            "Supplier: Amazon EU S.a.r.l.\n"
            "Total due: 89.99 EUR\n"
        )
        result = extract.parse_invoice_fields_from_text(text)
        self.assertEqual(result["Invoice Number"], "INV-2026-789")
        self.assertEqual(result["Invoice Date"], "2026-01-20")
        self.assertIn("Amazon", result["Supplier/Customer"])
        self.assertEqual(result["Gross Amount"], 89.99)

    def test_partial_fields_supplier_only(self):
        text = "Издател: Шел България ООД\nНякакъв текст без номер и дата.\n"
        result = extract.parse_invoice_fields_from_text(text)
        self.assertIn("Шел България", result["Supplier/Customer"])
        self.assertEqual(result["Invoice Number"], "")
        self.assertEqual(result["Invoice Date"], "")
        self.assertIsNone(result["Gross Amount"])

    def test_empty_text_returns_empty_fields(self):
        result = extract.parse_invoice_fields_from_text("")
        self.assertEqual(result["Supplier/Customer"], "")
        self.assertEqual(result["Invoice Number"], "")
        self.assertEqual(result["Invoice Date"], "")
        self.assertIsNone(result["Gross Amount"])

    def test_amount_with_spaces_and_commas(self):
        text = "Сума за плащане: 12 345,67 BGN\n"
        result = extract.parse_invoice_fields_from_text(text)
        self.assertEqual(result["Gross Amount"], 12345.67)

    def test_date_with_slash_separator(self):
        text = "Фактура 001\nДата: 05/11/2025\nОбщо: 50.00\n"
        result = extract.parse_invoice_fields_from_text(text)
        self.assertEqual(result["Invoice Date"], "2025-11-05")

    def test_multiple_amounts_picks_first_matching(self):
        text = (
            "Нетна стойност: 100.00\n"
            "ДДС: 20.00\n"
            "Общо за плащане: 120.00\n"
        )
        result = extract.parse_invoice_fields_from_text(text)
        self.assertEqual(result["Gross Amount"], 120.00)


class ParseMoneyTests(unittest.TestCase):
    """Tests for the internal _parse_money helper."""

    def test_simple_decimal(self):
        self.assertEqual(extract._parse_money("123.45"), 123.45)

    def test_comma_decimal(self):
        self.assertEqual(extract._parse_money("123,45"), 123.45)

    def test_thousands_separator(self):
        self.assertEqual(extract._parse_money("1.234,56"), 1234.56)

    def test_spaces_and_currency(self):
        self.assertEqual(extract._parse_money("1 234.56 лв"), 1234.56)

    def test_empty_string(self):
        self.assertIsNone(extract._parse_money(""))


class ToIsoDateTests(unittest.TestCase):
    """Tests for the internal _to_iso_date helper."""

    def test_dot_dmy(self):
        self.assertEqual(extract._to_iso_date("28.03.2026"), "2026-03-28")

    def test_dash_dmy(self):
        self.assertEqual(extract._to_iso_date("28-03-2026"), "2026-03-28")

    def test_iso_passthrough(self):
        self.assertEqual(extract._to_iso_date("2026-03-28"), "2026-03-28")

    def test_slash_dmy(self):
        self.assertEqual(extract._to_iso_date("28/03/2026"), "2026-03-28")

    def test_invalid_date(self):
        self.assertEqual(extract._to_iso_date("not-a-date"), "")


class ChooseInvoiceDateMultiLocaleTests(unittest.TestCase):
    """Tests for the multi-locale issue-date scorer."""

    def test_microinvest_due_date_suppressed(self):
        text = (
            "Microinvest Invoice Pro\n"
            "Номер: 0000000809\n"
            "Дата: 17.03.2026\n"
            "...\n"
            "Дата на падеж: 06.03.2026\n"
        )
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-17")

    def test_edocs_number_slash_date(self):
        text = (
            "Фактура ОРИГИНАЛ\n"
            "№ 0000000058 / 10.03.2026\n"
            "www.e-Docs.bg\n"
        )
        result = extract.parse_invoice_fields_from_text(text)
        self.assertEqual(result["Invoice Number"], "0000000058")
        self.assertEqual(result["Invoice Date"], "2026-03-10")

    def test_shopify_mar_9(self):
        text = "Bill #INV-100\nDate Mar 9, 2026\nBill paid Mar 9, 2026\nTotal $29.00\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-09")

    def test_suihe_27th_feb(self):
        text = "INVOICE\nDate: 27th Feb.,2026\nTotal: 100.00 USD\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-02-27")

    def test_liaocheng_march_25(self):
        text = "INVOICE\nDATE: MARCH 25, 2026\nTotal 50.00\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-25")

    def test_german_rechnungsdatum(self):
        text = (
            "Rechnung Nr. 12345\n"
            "Rechnungsdatum: 02.03.2026\n"
            "Fälligkeit: 16.03.2026\n"
        )
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-02")

    def test_chinese_cjk(self):
        text = "发票号: 12345\n开票日期：2026年3月2日\n到期日：2026年3月16日\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-02")

    def test_korean_cjk(self):
        text = "Invoice No 1\n발행일: 2026년 3월 2일\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-02")

    def test_eastern_arabic_digits(self):
        text = "Invoice\nDate: ٢٠٢٦/٠٣/٠٢\nTotal 100\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-02")

    def test_unambiguous_us_format(self):
        # Second number > 12 means MM/DD; first cannot be a day.
        text = "Date: 07/15/2026\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-07-15")

    def test_eu_default_when_first_above_12(self):
        # First > 12 means it MUST be the day → DMY.
        text = "Date: 15.03.2026\n"
        self.assertEqual(extract._choose_invoice_date(text), "2026-03-15")

    def test_empty_text(self):
        self.assertEqual(extract._choose_invoice_date(""), "")


class ChooseGrossAmountTests(unittest.TestCase):
    def test_returns_largest_gross(self):
        text = "Нетна стойност: 100.00\nДДС: 20.00\nОбщо за плащане: 120.00 лв.\n"
        gross, vat, net = extract._choose_gross_amount(text)
        self.assertEqual(gross, 120.0)
        self.assertEqual(vat, 20.0)
        self.assertEqual(net, 100.0)

    def test_currency_sniff_eur(self):
        text = "Total due: 89.99 EUR\n"
        self.assertEqual(extract._sniff_currency(text, default=""), "EUR")

    def test_currency_sniff_usd(self):
        text = "TOTAL: $123.45\n"
        self.assertEqual(extract._sniff_currency(text, default=""), "USD")


if __name__ == "__main__":
    unittest.main()
